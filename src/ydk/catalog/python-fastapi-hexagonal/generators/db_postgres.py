#!/usr/bin/env python3
"""Generate PostgreSQL full adapter implementation (SQLAlchemy async + repositories)"""

import json
import os
from pathlib import Path

import yaml
from _context.naming import derive_name, iter_fields


def to_snake(name: str) -> str:
    return "".join(["_" + c.lower() if c.isupper() else c for c in name]).lstrip("_")


SA_TYPE_MAP = {
    "str": "String",
    "int": "Integer",
    "float": "Float",
    "bool": "Boolean",
    "uuid": "UUID(as_uuid=True)",
    "datetime": "DateTime(timezone=True)",
    "date": "Date",
    "bytes": "LargeBinary",
    "json": "JSONB",
}


def sa_type(t: str) -> str:
    t = t.strip()
    if t.startswith("optional["):
        t = t[9:-1].strip()
    if " | None" in t:
        t = t.replace(" | None", "").strip()
    if t.startswith("list["):
        return "JSONB"
    return SA_TYPE_MAP.get(t, "String")


def generate_connection() -> str:
    return '''"""Database connection and session factory"""
from __future__ import annotations
import os
from sqlalchemy.ext.asyncio import (
    AsyncSession, create_async_engine, async_sessionmaker
)

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_async_engine(DATABASE_URL, pool_size=10, echo=False)
AsyncSessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncSession:
    async with AsyncSessionFactory() as session:
        yield session
'''


def generate_models(entities: list) -> str:
    lines = [
        '"""SQLAlchemy ORM models"""',
        "from __future__ import annotations",
        "import uuid",
        "from datetime import datetime, timezone",
        "from sqlalchemy import String, Boolean, Integer, Float, DateTime, Date, ForeignKey, Index",
        "from sqlalchemy.dialects.postgresql import UUID, JSONB",
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship",
        "",
        "",
        "class Base(DeclarativeBase):",
        "    pass",
        "",
    ]

    for entity in entities:
        name = derive_name(entity)
        table = to_snake(name) + "s"

        lines.append(f"\nclass {name}Model(Base):")
        lines.append(f'    __tablename__ = "{table}"')
        lines.append("")

        index_cols = []
        for fname, fdef in iter_fields(entity):
            ftype = fdef.get("type", "str")
            sa_t = sa_type(ftype)
            pk = fdef.get("primary_key", False)
            unique = fdef.get("unique", False)
            nullable = not fdef.get("required", True) or ftype.startswith("optional") or " | None" in ftype
            default = fdef.get("default")
            if fdef.get("index"):
                index_cols.append(fname)

            if pk:
                if "uuid" in ftype:
                    lines.append(
                        f"    {fname}: Mapped[uuid.UUID] = mapped_column("
                        f"UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)"
                    )
                else:
                    lines.append(f"    {fname}: Mapped[int] = mapped_column(primary_key=True)")
            elif unique:
                lines.append(f"    {fname}: Mapped[str] = mapped_column(String, nullable={nullable}, unique=True)")
            elif default == "now":
                lines.append(
                    f"    {fname}: Mapped[datetime] = mapped_column("
                    f"DateTime(timezone=True), nullable={nullable}, default=lambda: datetime.now(timezone.utc))"
                )
            else:
                py_type = {
                    "str": "str",
                    "int": "int",
                    "float": "float",
                    "bool": "bool",
                    "uuid": "uuid.UUID",
                    "datetime": "datetime",
                    "date": "datetime",
                    "bytes": "bytes",
                    "json": "dict",
                }.get(
                    ftype.replace("optional[", "").replace("]", "").replace(" | None", "").strip(),
                    "str",
                )
                mapped_sa = sa_t if "(" in sa_t else f"{sa_t}()"
                lines.append(f"    {fname}: Mapped[{py_type}] = mapped_column({mapped_sa}, nullable={nullable})")

        if index_cols:
            idx_str = ", ".join(f'Index("ix_{table}_{c}", "{c}")' for c in index_cols)
            lines.append(f"    __table_args__ = ({idx_str},)")

    return "\n".join(lines) + "\n"


def generate_repository(adapter: dict, port: dict) -> str:
    adapter_name = adapter["name"]
    port_name = adapter.get("implements", "")
    snake_port = to_snake(port_name)
    methods = port.get("methods", [])

    # Detect primary entity from port name pattern (UserRepositoryPort → User)
    entity_name = port_name.replace("RepositoryPort", "").replace("Port", "")

    method_impls = []
    for m in methods:
        mname = m["name"]
        args = m.get("args", [])
        returns = m.get("returns", "None")
        arg_str = ", ".join(f"{a['name']}: {a['type']}" for a in args)
        if arg_str:
            arg_str = ", " + arg_str
        method_impls.append(f"""
    async def {mname}(self{arg_str}) -> {returns}:
        raise NotImplementedError  # TODO: implement with SQLAlchemy""")

    return f'''"""Repository implementation stub — implement the methods"""
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from src.domain.ports.{snake_port} import {port_name}
from src.adapters.database.postgres.models import {entity_name}Model


class {adapter_name}({port_name}):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
{"".join(method_impls)}
'''


def main():
    dm_path = os.environ.get("YDK_COMPONENTS_ENTITY", "")
    ports_path = os.environ.get("YDK_COMPONENTS_CONTRACT", "")
    adapters_path = os.environ.get("YDK_COMPONENTS_ADAPTER", "")

    entities = []
    if dm_path and Path(dm_path).exists():
        entities = yaml.safe_load(Path(dm_path).read_text()) or {}
        entities = entities if isinstance(entities, list) else []

    ports_map = {}
    if ports_path and Path(ports_path).exists():
        pdata = yaml.safe_load(Path(ports_path).read_text()) or {}
        contracts_list = pdata if isinstance(pdata, list) else []
        all_ports = [port for c in contracts_list for port in c.get("ports", [])]
        ports_map = {p["name"]: p for p in all_ports}

    output = [
        {"path": "app/adapters/database/connection.py", "content": generate_connection()},
        {"path": "app/adapters/database/models.py", "content": generate_models(entities)},
    ]

    if adapters_path and Path(adapters_path).exists():
        adata = yaml.safe_load(Path(adapters_path).read_text()) or {}
        for adapter in adata.get("adapters", []):
            tech = adapter.get("technology", "")
            if "postgres" in tech.lower() or "sql" in tech.lower() or not tech:
                port = ports_map.get(adapter.get("implements", ""), {})
                snake = to_snake(adapter["name"])
                path = f"app/adapters/database/{snake}.py"
                output.append({"path": path, "content": generate_repository(adapter, port)})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

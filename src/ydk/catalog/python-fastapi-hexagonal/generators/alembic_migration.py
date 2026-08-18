#!/usr/bin/env python3
"""Generate Alembic migration files from data-model.yaml"""

import json
import os
from pathlib import Path

import yaml
from _context.naming import derive_table_name, iter_fields

ALEMBIC_ENV = '''"""Alembic environment configuration"""
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from src.adapters.database.postgres.models import Base  # noqa: E402
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}),
                                     prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
'''

SQL_TYPE_MAP = {
    "str": "sa.String()",
    "int": "sa.Integer()",
    "float": "sa.Float()",
    "bool": "sa.Boolean()",
    "uuid": "postgresql.UUID(as_uuid=True)",
    "datetime": "sa.DateTime(timezone=True)",
    "date": "sa.Date()",
    "bytes": "sa.LargeBinary()",
    "json": "postgresql.JSONB()",
}


def sa_type(t: str) -> str:
    t = t.strip()
    if t.startswith("optional["):
        t = t[9:-1].strip()
    if " | None" in t:
        t = t.replace(" | None", "").strip()
    if t.startswith("list["):
        return "postgresql.JSONB()"
    return SQL_TYPE_MAP.get(t, "sa.String()")


def generate_migration(entities: list) -> str:
    lines = [
        '"""Initial schema"""',
        "import sqlalchemy as sa",
        "from sqlalchemy.dialects import postgresql",
        "from alembic import op",
        "",
        "revision = '0001'",
        "down_revision = None",
        "branch_labels = None",
        "depends_on = None",
        "",
        "",
        "def upgrade() -> None:",
    ]
    for entity in entities:
        table = derive_table_name(entity)
        col_args = []
        for fn, fdef in iter_fields(entity):
            ft = sa_type(fdef.get("type", "str"))
            nullable = not fdef.get("required", True) or fdef.get("type", "").startswith("optional")
            pk = fdef.get("primary_key", False)
            default = fdef.get("default")
            parts = [f"'{fn}'", ft, f"nullable={nullable}"]
            if pk:
                parts.append("primary_key=True")
            if default == "uuid4":
                parts.append("server_default=sa.text('gen_random_uuid()')")
            elif default == "now":
                parts.append("server_default=sa.text('NOW()')")
            col_args.append(f"        sa.Column({', '.join(parts)}),")

        lines.append(f"    op.create_table('{table}',")
        lines.extend(col_args)
        lines.append("    )")
        for fn, fdef in iter_fields(entity):
            if fdef.get("index"):
                lines.append(f"    op.create_index('ix_{table}_{fn}', '{table}', ['{fn}'])")
        lines.append("")

    lines.extend(["", "def downgrade() -> None:"])
    for entity in reversed(entities):
        table = derive_table_name(entity)
        lines.append(f"    op.drop_table('{table}')")

    return "\n".join(lines)


def main():
    path = os.environ.get("YDK_COMPONENTS_ENTITY", "")
    if not path or not Path(path).exists():
        print("[]")
        return
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    entities = data if isinstance(data, list) else []
    output = [
        {"path": "env.py", "content": ALEMBIC_ENV},
        {"path": "versions/0001_initial.py", "content": generate_migration(entities)},
    ]
    print(json.dumps(output))


if __name__ == "__main__":
    main()

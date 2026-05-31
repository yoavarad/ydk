#!/usr/bin/env python3
"""Generate SQLite adapter implementation (aiosqlite + async)"""

import json
import os
from pathlib import Path

import yaml
from _context.naming import derive_name, iter_fields


def to_snake(name: str) -> str:
    return "".join(["_" + c.lower() if c.isupper() else c for c in name]).lstrip("_")


SQLITE_TYPE_MAP = {
    "str": "TEXT",
    "int": "INTEGER",
    "float": "REAL",
    "bool": "INTEGER",
    "uuid": "TEXT",
    "datetime": "TEXT",
    "date": "TEXT",
    "bytes": "BLOB",
    "json": "TEXT",
}


def sqlite_type(t: str) -> str:
    t = t.strip().replace("optional[", "").replace("]", "").replace(" | None", "").strip()
    if t.startswith("list["):
        return "TEXT"
    return SQLITE_TYPE_MAP.get(t, "TEXT")


def generate_sqlite_connection() -> str:
    return '''"""SQLite connection for development/testing"""
import os
import aiosqlite

DATABASE_PATH = os.environ["SQLITE_DATABASE_PATH"]


async def get_connection() -> aiosqlite.Connection:
    return await aiosqlite.connect(DATABASE_PATH)
'''


def generate_sqlite_schema(entities: list) -> str:
    stmts = ["-- SQLite schema", ""]
    for entity in entities:
        table = to_snake(derive_name(entity)) + "s"
        cols = []
        for fname, fdef in iter_fields(entity):
            col = f"  {fname} {sqlite_type(fdef.get('type', 'str'))}"
            if fdef.get("primary_key"):
                col += " PRIMARY KEY"
            if fdef.get("unique"):
                col += " UNIQUE"
            if (
                fdef.get("required", True)
                and not fdef.get("type", "").startswith("optional")
                and " | None" not in fdef.get("type", "")
            ):
                col += " NOT NULL"
            cols.append(col)
        stmts.append(f"CREATE TABLE IF NOT EXISTS {table} (\n" + ",\n".join(cols) + "\n);")
        stmts.append("")
    return "\n".join(stmts)


def main():
    dm_path = os.environ.get("ODK_COMPONENTS_ENTITY", "")
    if not dm_path or not Path(dm_path).exists():
        print("[]")
        return
    data = yaml.safe_load(Path(dm_path).read_text()) or {}
    entities = data if isinstance(data, list) else []
    output = [
        {"path": "connection.py", "content": generate_sqlite_connection()},
        {"path": "schema.sql", "content": generate_sqlite_schema(entities)},
    ]
    print(json.dumps(output))


if __name__ == "__main__":
    main()

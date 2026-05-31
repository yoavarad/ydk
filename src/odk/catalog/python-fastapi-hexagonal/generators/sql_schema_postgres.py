#!/usr/bin/env python3
"""Generate PostgreSQL DDL CREATE TABLE from ODK entity components"""

import json
import os
from pathlib import Path

import yaml
from _context.naming import derive_name, iter_fields

SQL_TYPE_MAP = {
    "str": "TEXT",
    "int": "INTEGER",
    "float": "FLOAT",
    "bool": "BOOLEAN",
    "uuid": "UUID",
    "datetime": "TIMESTAMPTZ",
    "date": "DATE",
    "bytes": "BYTEA",
    "json": "JSONB",
}


def map_sql_type(t: str) -> str:
    t = t.strip()
    if t.startswith("optional["):
        t = t[9:-1].strip()
    if " | None" in t:
        t = t.replace(" | None", "").strip()
    if t.startswith("list["):
        return "JSONB"
    return SQL_TYPE_MAP.get(t, "TEXT")


def generate_table(entity: dict) -> str:
    name = derive_name(entity).lower() + "s"  # pluralize
    columns = []
    constraints = []
    indices = []

    for fname, fdef in iter_fields(entity):
        ftype = map_sql_type(fdef.get("type", "str"))
        required = fdef.get("required", True)
        pk = fdef.get("primary_key", False)
        unique = fdef.get("unique", False)
        default = fdef.get("default")
        index = fdef.get("index", False)

        col = f"    {fname} {ftype}"
        if not fdef.get("type", "").startswith("optional") and " | None" not in fdef.get("type", "") and required:
            col += " NOT NULL"
        if default == "uuid4":
            col += " DEFAULT gen_random_uuid()"
        elif default == "now":
            col += " DEFAULT NOW()"
        elif default is not None and not callable(default):
            col += f" DEFAULT {repr(default)}"
        if pk:
            constraints.append(f"    PRIMARY KEY ({fname})")
        if unique:
            constraints.append(f"    UNIQUE ({fname})")
        if index:
            indices.append(f"CREATE INDEX IF NOT EXISTS ix_{name}_{fname} ON {name} ({fname});")
        columns.append(col)

    all_cols = columns + constraints
    table_def = f"CREATE TABLE IF NOT EXISTS {name} (\n" + ",\n".join(all_cols) + "\n);"
    idx_defs = "\n".join(indices)
    return table_def + ("\n" + idx_defs if idx_defs else "")


def main():
    path = os.environ.get("ODK_COMPONENTS_ENTITY", "")
    if not path or not Path(path).exists():
        print("[]")
        return
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    tables = ["-- PostgreSQL schema", ""]
    for entity in data if isinstance(data, list) else []:
        tables.append(generate_table(entity))
        tables.append("")

    print(json.dumps([{"path": "schema.sql", "content": "\n".join(tables)}]))


if __name__ == "__main__":
    main()

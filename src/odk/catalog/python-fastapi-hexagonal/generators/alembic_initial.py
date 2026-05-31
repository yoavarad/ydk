#!/usr/bin/env python3
"""
Generator: alembic-initial
Generate initial Alembic migration from data-model.yaml.
Input: data-model.yaml
Output: alembic/versions/{timestamp}_0001_initial_schema.py + env.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add generators dir to path for _context imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _context.naming import derive_table_name, iter_fields, to_snake
from jinja2 import Environment, FileSystemLoader, StrictUndefined

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


def _pluralize(name: str) -> str:
    """Convert PascalCase model name to correct snake_case table name."""
    snake = to_snake(name)
    if (
        snake.endswith("ies")
        or snake.endswith("ses")
        or snake.endswith("ches")
        or snake.endswith("xes")
        or snake.endswith("zes")
        or snake.endswith("shes")
    ):
        return snake
    if snake.endswith("s"):
        return snake
    if snake.endswith("y") and not snake.endswith(("ay", "ey", "oy", "uy")):
        return snake[:-1] + "ies"
    elif snake.endswith(("sh", "ch", "x", "z")):
        return snake + "es"
    else:
        return snake + "s"


def sa_type(t: str) -> str:
    t = t.strip()
    if t.startswith("optional["):
        t = t[9:-1].strip()
    if " | None" in t:
        t = t.replace(" | None", "").strip()
    if t.startswith("list["):
        return "postgresql.JSONB()"
    return SQL_TYPE_MAP.get(t, "sa.String()")


def build_context(entities: list) -> dict:
    """Build the Jinja2 template context for the initial migration."""
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    entity_contexts = []
    for entity in entities:
        table = derive_table_name(entity)
        columns = []
        for fname, fdef in iter_fields(entity):
            ftype = fdef.get("type", "str")
            pk = fdef.get("primary_key", False)
            unique = fdef.get("unique", False)
            nullable = not fdef.get("required", True) or ftype.startswith("optional") or "| None" in ftype
            col_type = sa_type(ftype)
            extras = []
            if pk:
                extras.append("primary_key=True")
            if not nullable and not pk:
                extras.append("nullable=False")
            if unique:
                extras.append("unique=True")
            extras_str = (", " + ", ".join(extras)) if extras else ""
            columns.append({"name": fname, "sa_type": col_type, "extras": extras_str})
        entity_contexts.append({"table_name": table, "columns": columns})

    entities_reversed = list(reversed(entity_contexts))

    return {
        "timestamp": timestamp,
        "entities": entity_contexts,
        "entities_reversed": entities_reversed,
    }


def main() -> None:
    path = os.environ.get("ODK_COMPONENTS_ENTITY", "")
    if not path or not Path(path).exists():
        print("[]")
        return

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    entities = data if isinstance(data, list) else []
    if not entities:
        print("[]")
        return

    # Set up Jinja2
    templates_dir = Path(__file__).parent.parent / "templates" / "migrations"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    context = build_context(entities)
    timestamp = context["timestamp"]

    migration_template = env.get_template("initial.py.j2")
    migration_content = migration_template.render(**context).rstrip() + "\n"

    env_template = env.get_template("env.py.j2")
    env_content = env_template.render().rstrip() + "\n"

    output = [
        {"path": f"alembic/versions/{timestamp}_0001_initial_schema.py", "content": migration_content},
        {"path": "alembic/env.py", "content": env_content},
    ]
    print(json.dumps(output))


if __name__ == "__main__":
    main()

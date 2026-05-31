#!/usr/bin/env python3
"""
Generator: db-postgres-repos
Generates full CRUD repository adapter implementations per entity.
Input: ODK entity components
Output: app/adapters/database/repos/{entity_snake}_repository.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add generators dir to path for _context imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _context.naming import derive_name, has_updated_at, iter_fields, list_filter_params, pk_type, to_snake
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def build_entity_context(entity: dict) -> dict:
    """Build the Jinja2 template context for one entity."""
    name = derive_name(entity)
    has_ts = any(fname in ("created_at", "updated_at") for fname, _ in iter_fields(entity))
    return {
        "name": name,
        "snake_name": to_snake(name),
        "pk_type": pk_type(entity),
        "list_params": list_filter_params(entity),
        "has_timestamps": has_ts,
        "has_updated_at": has_updated_at(entity),
    }


def main() -> None:
    artifact_path = os.environ.get("ODK_COMPONENTS_ENTITY", "")
    if not artifact_path or not Path(artifact_path).exists():
        print("Error: ODK_COMPONENTS_ENTITY not set or file not found", file=sys.stderr)
        sys.exit(1)

    data = yaml.safe_load(Path(artifact_path).read_text())
    entities = data if isinstance(data, list) else []

    # Set up Jinja2
    templates_dir = Path(__file__).parent.parent / "templates" / "repos"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("postgres_repo.py.j2")

    output = []
    for entity in entities:
        context = build_entity_context(entity)
        content = template.render(**context).rstrip() + "\n"
        path = f"app/adapters/database/repos/{context['snake_name']}_repository.py"
        output.append({"path": path, "content": content})

    # Generate __init__.py that exports all repo classes (sorted for stable import order)
    init_lines = []
    for entity in sorted(entities, key=lambda e: to_snake(derive_name(e)) + "_repository"):
        name = derive_name(entity)
        snake_name = to_snake(name)
        module = f"app.adapters.database.repos.{snake_name}_repository"
        cls = f"Postgres{name}Repository"
        single = f"from {module} import {cls} as {cls}"
        if len(single) <= 99:
            init_lines.append(single)
        else:
            init_lines.append(f"from {module} import (")
            init_lines.append(f"    {cls} as {cls},")
            init_lines.append(")")
    if init_lines:
        output.append({"path": "app/adapters/database/repos/__init__.py", "content": "\n".join(init_lines) + "\n"})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

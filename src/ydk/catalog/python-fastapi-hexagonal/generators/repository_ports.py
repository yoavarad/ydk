#!/usr/bin/env python3
"""
Generator: repository-ports
Generates @runtime_checkable Protocol repository interfaces per entity.
Each entity gets: get, list, create, update, delete, exists methods.
Input: YDK entity components
Output: app/core/ports/{entity_snake}_repository.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add generators dir to path for _context imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _context.naming import derive_name, list_filter_params, pk_type, to_snake
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def build_entity_context(entity: dict) -> dict:
    """Build the Jinja2 template context for one entity."""
    name = derive_name(entity)
    return {
        "name": name,
        "snake_name": to_snake(name),
        "pk_type": pk_type(entity),
        "list_params": list_filter_params(entity),
    }


def main() -> None:
    artifact_path = os.environ.get("YDK_COMPONENTS_ENTITY", "")
    if not artifact_path or not Path(artifact_path).exists():
        print("Error: YDK_COMPONENTS_ENTITY not set or file not found", file=sys.stderr)
        sys.exit(1)

    data = yaml.safe_load(Path(artifact_path).read_text())
    entities = data if isinstance(data, list) else []

    # Set up Jinja2
    templates_dir = Path(__file__).parent.parent / "templates" / "ports"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("repository_port.py.j2")

    output = []
    for entity in entities:
        context = build_entity_context(entity)
        content = template.render(**context).rstrip() + "\n"
        output.append({"path": f"app/core/ports/{context['snake_name']}_repository.py", "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

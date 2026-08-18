#!/usr/bin/env python3
"""
Generator: fake-repos
Generate in-memory FakeXxxRepository for each entity — fully functional, no DB needed.
Input: YDK entity components
Output: tests/fakes/fake_{entity}_repository.py per entity
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
    """Build the Jinja2 template context for one entity fake repository."""
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

    data = yaml.safe_load(Path(artifact_path).read_text(encoding="utf-8"))
    entities = data if isinstance(data, list) else []

    # Set up Jinja2
    templates_dir = Path(__file__).parent.parent / "templates" / "tests"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("fake_repository.py.j2")

    output = []
    for entity in entities:
        context = build_entity_context(entity)
        content = template.render(**context).rstrip() + "\n"
        output.append({"path": f"tests/fakes/fake_{context['snake_name']}_repository.py", "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

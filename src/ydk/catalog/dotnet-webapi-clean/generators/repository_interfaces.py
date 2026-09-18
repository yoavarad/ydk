#!/usr/bin/env python3
"""
Generator: repository-interfaces
Generates Application-layer repository interfaces per entity, with standard
CRUD method signatures (GetByIdAsync, ListAsync, AddAsync, UpdateAsync, DeleteAsync).

Input: YDK entity components (contract components are declared as an input in
the manifest for future generators in this pack, but are not needed here).
Output: Application/Interfaces/I{Name}Repository.cs
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add generators dir to path for local helper imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _dotnet_common import derive_name, pk_field
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def build_entity_context(entity: dict) -> dict:
    """Build the Jinja2 template context for one entity."""
    name = derive_name(entity)
    _pk_name, pk_type = pk_field(entity)
    return {"name": name, "pk_type": pk_type}


def main() -> None:
    artifact_path = os.environ.get("YDK_COMPONENTS_ENTITY", "")
    if not artifact_path or not Path(artifact_path).exists():
        print("Error: YDK_COMPONENTS_ENTITY not set or file not found", file=sys.stderr)
        sys.exit(1)

    data = yaml.safe_load(Path(artifact_path).read_text(encoding="utf-8"))
    entities = data if isinstance(data, list) else []

    templates_dir = Path(__file__).parent.parent / "templates" / "application"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("repository_interface.cs.j2")

    output = []
    for entity in entities:
        context = build_entity_context(entity)
        content = template.render(**context).rstrip() + "\n"
        output.append({"path": f"Application/Interfaces/I{context['name']}Repository.cs", "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

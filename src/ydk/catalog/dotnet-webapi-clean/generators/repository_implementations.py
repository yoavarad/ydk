#!/usr/bin/env python3
"""
Generator: repository-implementations
Generates EF Core-backed Infrastructure-layer implementations of each entity's
I{Name}Repository, using AppDbContext (constructor-injected) against DbSet<{Name}>.

Input: YDK entity components
Output: Infrastructure/Persistence/Repositories/{Name}Repository.cs
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add generators dir to path for local helper imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _dotnet_common import derive_name, pk_field, pluralize
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def build_entity_context(entity: dict) -> dict:
    """Build the Jinja2 template context for one entity."""
    name = derive_name(entity)
    _pk_name, pk_type = pk_field(entity)
    return {"name": name, "pk_type": pk_type, "dbset_name": pluralize(name)}


def main() -> None:
    artifact_path = os.environ.get("YDK_COMPONENTS_ENTITY", "")
    if not artifact_path or not Path(artifact_path).exists():
        print("Error: YDK_COMPONENTS_ENTITY not set or file not found", file=sys.stderr)
        sys.exit(1)

    data = yaml.safe_load(Path(artifact_path).read_text(encoding="utf-8"))
    entities = data if isinstance(data, list) else []

    templates_dir = Path(__file__).parent.parent / "templates" / "infrastructure"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("repository_impl.cs.j2")

    output = []
    for entity in entities:
        context = build_entity_context(entity)
        content = template.render(**context).rstrip() + "\n"
        output.append(
            {
                "path": f"Infrastructure/Persistence/Repositories/{context['name']}Repository.cs",
                "content": content,
            }
        )

    print(json.dumps(output))


if __name__ == "__main__":
    main()

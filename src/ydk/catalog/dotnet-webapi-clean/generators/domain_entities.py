#!/usr/bin/env python3
"""
Generator: domain-entities
Generates plain C# POCO domain entity classes from YDK entity components.
Input: YDK_COMPONENTS_ENTITY
Output: Domain/Entities/{Name}.cs per entity
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add generators dir to path for local helper import
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _dotnet_common import csharp_type, derive_entity_name, iter_fields, project_namespace, to_pascal_case
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def build_entity_context(entity: dict, namespace: str) -> dict:
    """Build the Jinja2 template context for one entity's POCO class."""
    properties = []
    for fname, fdef in iter_fields(entity):
        prop_type = csharp_type(fdef)
        suffix = " = string.Empty;" if prop_type == "string" else ""
        properties.append(
            {
                "name": to_pascal_case(fname),
                "type": prop_type,
                "suffix": suffix,
            }
        )

    return {
        "namespace": f"{namespace}.Domain.Entities",
        "name": derive_entity_name(entity),
        "properties": properties,
    }


def main() -> None:
    entity_path = os.environ.get("YDK_COMPONENTS_ENTITY", "")
    if not entity_path or not Path(entity_path).exists():
        print("Error: YDK_COMPONENTS_ENTITY not set or file not found", file=sys.stderr)
        sys.exit(1)

    entities = yaml.safe_load(Path(entity_path).read_text())
    if not isinstance(entities, list):
        entities = []

    namespace = project_namespace()

    templates_dir = Path(__file__).parent.parent / "templates" / "domain"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("entity.cs.j2")

    output = []
    for entity in entities:
        context = build_entity_context(entity, namespace)
        content = template.render(**context).rstrip() + "\n"
        output.append({"path": f"Domain/Entities/{context['name']}.cs", "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

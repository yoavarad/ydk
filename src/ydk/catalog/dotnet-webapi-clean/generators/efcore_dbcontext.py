#!/usr/bin/env python3
"""
Generator: efcore-dbcontext
Generates the EF Core AppDbContext and per-entity IEntityTypeConfiguration classes
from YDK entity components. Defaults to the SQLite provider (see
docs/adrs/0001-dotnet-webapi-clean-defaults.md).
Input: YDK_COMPONENTS_ENTITY
Output:
  - Infrastructure/Persistence/AppDbContext.cs
  - Infrastructure/Persistence/Configurations/{Name}Configuration.cs per entity
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add generators dir to path for local helper import
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _dotnet_common import derive_entity_name, iter_fields, pluralize, project_namespace, to_pascal_case
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def _build_property_chain(fdef: dict) -> str:
    """Build the fluent-API chain suffix for one property's configuration, e.g.
    ``.IsRequired().HasMaxLength(200)``. Empty string when nothing to configure."""
    ftype = str(fdef.get("type", "string")).lower()
    chain_parts: list[str] = []

    required = (bool(fdef.get("required")) or fdef.get("nullable") is False) and not fdef.get("primary_key")
    if required:
        chain_parts.append(".IsRequired()")

    max_length = fdef.get("max_length")
    if max_length and ftype in ("string", "text"):
        chain_parts.append(f".HasMaxLength({max_length})")

    precision = fdef.get("precision")
    if ftype == "decimal" and isinstance(precision, list) and len(precision) == 2:
        chain_parts.append(f".HasPrecision({precision[0]}, {precision[1]})")

    return "".join(chain_parts)


def build_dbcontext_context(entities: list[dict], namespace: str) -> dict:
    """Build the Jinja2 template context for AppDbContext.cs."""
    entity_list = []
    for entity in entities:
        name = derive_entity_name(entity)
        entity_list.append({"name": name, "dbset_name": pluralize(name)})

    return {
        "namespace": f"{namespace}.Infrastructure.Persistence",
        "entity_namespace": f"{namespace}.Domain.Entities",
        "entities": entity_list,
    }


def build_configuration_context(entity: dict, namespace: str) -> dict:
    """Build the Jinja2 template context for one entity's {Name}Configuration.cs."""
    name = derive_entity_name(entity)
    pk_property = None
    properties = []
    for fname, fdef in iter_fields(entity):
        if fdef.get("primary_key"):
            pk_property = to_pascal_case(fname)
        chain = _build_property_chain(fdef)
        if chain:
            properties.append({"name": to_pascal_case(fname), "chain": chain})

    if pk_property is None:
        msg = f"Entity '{name}' has no field with primary_key: true; cannot generate EF Core configuration."
        raise ValueError(msg)

    table_name = entity.get("table_name") or pluralize(name)

    return {
        "namespace": f"{namespace}.Infrastructure.Persistence.Configurations",
        "entity_namespace": f"{namespace}.Domain.Entities",
        "name": name,
        "table_name": table_name,
        "pk_property": pk_property,
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

    templates_dir = Path(__file__).parent.parent / "templates" / "infrastructure"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    output = []

    dbcontext_template = env.get_template("dbcontext.cs.j2")
    dbcontext_context = build_dbcontext_context(entities, namespace)
    content = dbcontext_template.render(**dbcontext_context).rstrip() + "\n"
    output.append({"path": "Infrastructure/Persistence/AppDbContext.cs", "content": content})

    config_template = env.get_template("entity_configuration.cs.j2")
    for entity in entities:
        try:
            context = build_configuration_context(entity, namespace)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        content = config_template.render(**context).rstrip() + "\n"
        output.append(
            {
                "path": f"Infrastructure/Persistence/Configurations/{context['name']}Configuration.cs",
                "content": content,
            }
        )

    print(json.dumps(output))


if __name__ == "__main__":
    main()

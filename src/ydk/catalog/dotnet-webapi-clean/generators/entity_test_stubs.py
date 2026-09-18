#!/usr/bin/env python3
"""
Generator: entity-test-stubs
Generates basic xUnit tests per entity for the plain POCO classes emitted by
domain_entities.py (task #104): assigns a sample value to every property and
asserts it round-trips through the auto-implemented getter/setter.

This satisfies the dotnet-tdd-guard verification plugin
(src/ydk/verifications/dotnet-tdd-guard/check.py), which requires every
staged .cs file outside a Tests-named directory to have a matching
{Stem}Tests.cs somewhere under a `Tests`/`*.Tests` directory: Domain/Entities/
{Name}.cs (domain_entities.py) is satisfied by this generator's
{Solution}.Tests/Domain/{Name}Tests.cs (a `*.Tests`-suffixed directory).

Input: YDK entity components
Output: {Solution}.Tests/Domain/{Name}Tests.cs
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add generators dir to path for local helper imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _dotnet_common import csharp_type, derive_name, iter_fields, to_camel, to_pascal_case
from jinja2 import Environment, FileSystemLoader, StrictUndefined

TESTS_DIR = "WebApiClean.Tests"

_SAMPLE_VALUES = {
    "string": '"sample"',
    "int": "1",
    "long": "1L",
    "decimal": "1m",
    "double": "1.0",
    "bool": "true",
    "Guid": "Guid.NewGuid()",
    "DateTime": "DateTime.UtcNow",
    "DateOnly": "DateOnly.FromDateTime(DateTime.UtcNow)",
}


def _sample_value(prop_type: str) -> str:
    """A valid C# literal/expression assignable to a property of `prop_type`."""
    base_type = prop_type[:-1] if prop_type.endswith("?") else prop_type
    return _SAMPLE_VALUES.get(base_type, "default")


def build_entity_context(entity: dict) -> dict:
    """Build the Jinja2 template context for one entity's property round-trip test."""
    properties = []
    for fname, fdef in iter_fields(entity):
        prop_type = csharp_type(fdef)
        prop_name = to_pascal_case(fname)
        properties.append(
            {"name": prop_name, "sample": _sample_value(prop_type), "var_name": f"{to_camel(prop_name)}Value"}
        )
    return {"name": derive_name(entity), "properties": properties}


def main() -> None:
    entity_path = os.environ.get("YDK_COMPONENTS_ENTITY", "")
    if not entity_path or not Path(entity_path).exists():
        print("Error: YDK_COMPONENTS_ENTITY not set or file not found", file=sys.stderr)
        sys.exit(1)

    data = yaml.safe_load(Path(entity_path).read_text(encoding="utf-8"))
    entities = data if isinstance(data, list) else []

    templates_dir = Path(__file__).parent.parent / "templates" / "tests"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("entity_test.cs.j2")

    output = []
    for entity in entities:
        context = build_entity_context(entity)
        content = template.render(**context).rstrip() + "\n"
        output.append({"path": f"{TESTS_DIR}/Domain/{context['name']}Tests.cs", "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

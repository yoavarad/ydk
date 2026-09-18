#!/usr/bin/env python3
"""
Generator: fake-repositories
Generates an in-memory fake implementation of each entity's I{Name}Repository
(from repository_interfaces.py, task #105) for use by unit test stubs --
backed by a Dictionary<PkType, {Name}> instead of EF Core.

Input: YDK entity components
Output: {Solution}.Tests/Fakes/Fake{Name}Repository.cs
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add generators dir to path for local helper imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _dotnet_common import derive_name, pk_field, to_pascal_case
from jinja2 import Environment, FileSystemLoader, StrictUndefined

# Fixed Tests project directory name -- matches solution_scaffold.py's
# ROOT_NAMESPACE-based tests project ("WebApiClean.Tests"), unconditionally.
TESTS_DIR = "WebApiClean.Tests"


def build_entity_context(entity: dict) -> dict:
    """Build the Jinja2 template context for one entity's fake repository."""
    name = derive_name(entity)
    pk_name, pk_type = pk_field(entity)
    return {"name": name, "pk_type": pk_type, "pk_property": to_pascal_case(pk_name)}


def main() -> None:
    artifact_path = os.environ.get("YDK_COMPONENTS_ENTITY", "")
    if not artifact_path or not Path(artifact_path).exists():
        print("Error: YDK_COMPONENTS_ENTITY not set or file not found", file=sys.stderr)
        sys.exit(1)

    data = yaml.safe_load(Path(artifact_path).read_text(encoding="utf-8"))
    entities = data if isinstance(data, list) else []

    templates_dir = Path(__file__).parent.parent / "templates" / "tests"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("fake_repository.cs.j2")

    output = []
    for entity in entities:
        context = build_entity_context(entity)
        content = template.render(**context).rstrip() + "\n"
        output.append({"path": f"{TESTS_DIR}/Fakes/Fake{context['name']}Repository.cs", "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

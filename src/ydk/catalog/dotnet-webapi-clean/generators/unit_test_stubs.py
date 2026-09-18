#!/usr/bin/env python3
"""
Generator: unit-test-stubs
Generates xUnit test class stubs per contract, exercising the generated
{Name}Service (service_stubs.py, task #105) against its Fake{Name}Repository
(fake_repositories.py, this task) -- one test method per contract operation.

Since every service method currently stubs `throw new NotImplementedException();`
(task #105), each test asserts that behavior today; a developer replaces the
assertion with real expectations once the method is implemented.

Input: YDK contract + entity components (entities are used to seed sample
argument values for entity-typed parameters).
Output: {Solution}.Tests/Services/{Name}ServiceTests.cs
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add generators dir to path for local helper imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _dotnet_common import contract_methods, service_and_entity_name, to_camel
from jinja2 import Environment, FileSystemLoader, StrictUndefined

TESTS_DIR = "WebApiClean.Tests"

# Sample literal per C# primitive/base type, used to build a valid call to a
# stub service method so the test compiles. Nullable params always pass null.
_SAMPLE_LITERALS = {
    "string": '"test"',
    "int": "1",
    "long": "1L",
    "double": "1.0",
    "decimal": "1m",
    "bool": "true",
    "Guid": "Guid.NewGuid()",
    "DateTime": "DateTime.UtcNow",
    "DateOnly": "DateOnly.FromDateTime(DateTime.UtcNow)",
    "byte[]": "Array.Empty<byte>()",
    "object": "new object()",
}


def _sample_arg(csharp_type: str) -> str:
    """A valid C# expression usable as an argument value for `csharp_type`."""
    if csharp_type.endswith("?"):
        return "null"
    if csharp_type in _SAMPLE_LITERALS:
        return _SAMPLE_LITERALS[csharp_type]
    if csharp_type.startswith("IEnumerable<") and csharp_type.endswith(">"):
        inner = csharp_type[len("IEnumerable<") : -1]
        return f"new List<{inner}>()"
    # Unknown type: assume it's a reference type with a parameterless constructor
    # (e.g. an entity class from Domain.Entities).
    return f"new {csharp_type}()"


def build_contract_context(contract: dict) -> dict:
    """Build the Jinja2 template context for one contract's test class."""
    service_name, entity_name = service_and_entity_name(contract)
    methods = []
    for method in contract_methods(contract):
        args = ", ".join(_sample_arg(p["type"]) for p in method["params"])
        methods.append({"name": method["name"], "args": args})
    return {
        "service_name": service_name,
        "repo_param": to_camel(f"{entity_name}Repository"),
        "fake_repo_type": f"Fake{entity_name}Repository",
        "methods": methods,
    }


def main() -> None:
    contract_path = os.environ.get("YDK_COMPONENTS_CONTRACT", "")
    if not contract_path or not Path(contract_path).exists():
        print("Error: YDK_COMPONENTS_CONTRACT not set or file not found", file=sys.stderr)
        sys.exit(1)

    data = yaml.safe_load(Path(contract_path).read_text(encoding="utf-8"))
    contracts = data if isinstance(data, list) else []

    # entity is declared as an input in manifest.yaml (for parity with other
    # Application-layer generators) but isn't needed here: contract_methods()
    # + _sample_arg() already produce a valid call for every parameter type
    # without inspecting entity field definitions.

    templates_dir = Path(__file__).parent.parent / "templates" / "tests"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("service_test.cs.j2")

    output = []
    for contract in contracts:
        context = build_contract_context(contract)
        content = template.render(**context).rstrip() + "\n"
        output.append({"path": f"{TESTS_DIR}/Services/{context['service_name']}Tests.cs", "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

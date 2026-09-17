#!/usr/bin/env python3
"""
Generator: service-stubs
Generates Application-layer service interface + class stubs per contract.
Each service is constructor-injected with the relevant I{Name}Repository; every
method body is `throw new NotImplementedException();` -- business logic is filled
in later by a human/agent. Task #109 scans generated .cs files for this exact
string to register tracked TODOs, so the stub body must match it verbatim.

Input: YDK contract components
Output: Application/Services/{Name}Service.cs + Application/Services/I{Name}Service.cs
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


def build_contract_context(contract: dict) -> dict:
    """Build the Jinja2 template context for one contract."""
    service_name, entity_name = service_and_entity_name(contract)
    return {
        "service_name": service_name,
        "entity_name": entity_name,
        "repo_param": to_camel(f"{entity_name}Repository"),
        "methods": contract_methods(contract),
    }


def main() -> None:
    artifact_path = os.environ.get("YDK_COMPONENTS_CONTRACT", "")
    if not artifact_path or not Path(artifact_path).exists():
        print("Error: YDK_COMPONENTS_CONTRACT not set or file not found", file=sys.stderr)
        sys.exit(1)

    data = yaml.safe_load(Path(artifact_path).read_text(encoding="utf-8"))
    contracts = data if isinstance(data, list) else []

    templates_dir = Path(__file__).parent.parent / "templates" / "application"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    interface_template = env.get_template("service_interface.cs.j2")
    stub_template = env.get_template("service_stub.cs.j2")

    output = []
    for contract in contracts:
        context = build_contract_context(contract)
        service_name = context["service_name"]

        interface_content = interface_template.render(**context).rstrip() + "\n"
        output.append({"path": f"Application/Services/I{service_name}.cs", "content": interface_content})

        stub_content = stub_template.render(**context).rstrip() + "\n"
        output.append({"path": f"Application/Services/{service_name}.cs", "content": stub_content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

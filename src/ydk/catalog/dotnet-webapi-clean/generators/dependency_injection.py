#!/usr/bin/env python3
"""
Generator: dependency-injection
Generates the Api-layer IServiceCollection extension that wires the EF Core
AppDbContext (SQLite), every entity's I{Name}Repository -> {Name}Repository, and
every contract's I{Name}Service -> {Name}Service as scoped services.

Input: YDK entity + contract components
Output: Api/ServiceCollectionExtensions.cs
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add generators dir to path for local helper imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _dotnet_common import derive_name, service_and_entity_name
from jinja2 import Environment, FileSystemLoader, StrictUndefined

# Fixed, unprefixed namespace -- matches AppDbContext's namespace as declared
# by efcore_dbcontext.py (not derived from project_namespace()/YDK_PROJECT_ROOT,
# so it always matches).
DBCONTEXT_NAMESPACE = "Infrastructure.Persistence"


def build_context(entities: list[dict], contracts: list[dict]) -> dict:
    """Build the Jinja2 template context for ServiceCollectionExtensions.cs."""
    repositories = []
    for entity in entities:
        name = derive_name(entity)
        repositories.append({"interface": f"I{name}Repository", "implementation": f"{name}Repository"})

    services = []
    for contract in contracts:
        service_name, _entity_name = service_and_entity_name(contract)
        services.append({"interface": f"I{service_name}", "implementation": service_name})

    return {
        "dbcontext_namespace": DBCONTEXT_NAMESPACE,
        "repositories": repositories,
        "services": services,
    }


def _load_components(env_var: str) -> list[dict]:
    path = os.environ.get(env_var, "")
    if not path or not Path(path).exists():
        print(f"Error: {env_var} not set or file not found", file=sys.stderr)
        sys.exit(1)
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def main() -> None:
    entities = _load_components("YDK_COMPONENTS_ENTITY")
    contracts = _load_components("YDK_COMPONENTS_CONTRACT")

    templates_dir = Path(__file__).parent.parent / "templates" / "api"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("service_collection_extensions.cs.j2")

    context = build_context(entities, contracts)
    content = template.render(**context).rstrip() + "\n"

    print(json.dumps([{"path": "Api/ServiceCollectionExtensions.cs", "content": content}]))


if __name__ == "__main__":
    main()

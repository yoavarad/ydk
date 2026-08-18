#!/usr/bin/env python3
"""
Generator: unit-test-stubs
Generate service unit test stubs with fake fixtures and TODO markers.
Input: YDK contract components, YDK entity components
Output: tests/unit/core/services/test_{service}_service.py per service
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add generators dir to path for _context imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _context.naming import derive_name, port_module_name, to_snake
from _context.todos import test_todo
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def _repo_entity_from_port(port_name: str) -> str | None:
    """
    Infer entity name from a port name ending in 'RepositoryPort'.
    e.g. StrategyRepositoryPort → Strategy
    """
    if port_name.endswith("RepositoryPort"):
        return port_name[: -len("RepositoryPort")]
    return None


def build_service_context(uc: dict, entity_names: set[str]) -> dict:
    """Build the Jinja2 template context for one service unit test file."""
    name = derive_name(uc)
    # Strip trailing "Service" for base name, then add back for service class name
    service_name = name if name.endswith("Service") else f"{name}Service"
    base_name = service_name[: -len("Service")] if service_name.endswith("Service") else service_name

    raw_ports = uc.get("ports", [])
    ports = [p["name"] if isinstance(p, dict) else p for p in raw_ports]
    methods_src = uc.get("methods", {})
    # Normalize YDK map-format methods to list format
    if isinstance(methods_src, dict):
        methods_raw = [
            {"name": mname, **(mdef if isinstance(mdef, dict) else {})} for mname, mdef in methods_src.items()
        ]
    else:
        methods_raw = methods_src

    # Handle all port dependencies: repository ports get fakes, other ports get fakes too
    repo_deps = []
    fake_imports = []
    repo_port_imports = []

    for port in ports:
        entity = _repo_entity_from_port(port)
        if entity and entity in entity_names:
            # Repository port — use existing fake repository pattern
            snake_entity = to_snake(entity)
            fake_class = f"Fake{entity}Repository"
            fixture_name = f"fake_{snake_entity}_repo"
            param_name = to_snake(port)  # e.g. strategy_repository_port
            fake_imports.append(f"from tests.fakes.fake_{snake_entity}_repository import {fake_class}")
            repo_port_imports.append(f"from app.core.ports.{snake_entity}_repository import {entity}RepositoryPort")
            repo_deps.append(
                {
                    "fixture_name": fixture_name,
                    "fake_class": fake_class,
                    "param_name": param_name,
                }
            )
        else:
            # Non-repository port (e.g. EventBusPort) — import from fake_ports generator
            # fake_ports.py strips "Port" suffix: EventBusPort -> FakeEventBus in fake_event_bus.py
            port_module = port_module_name(port)  # e.g. "event_bus"
            bare_name = port.removesuffix("Port") if port.endswith("Port") else port
            fake_class = f"Fake{bare_name}"
            fixture_name = f"fake_{port_module}"
            param_name = to_snake(port)  # e.g. "event_bus_port" for DI param name
            fake_imports.append(f"from tests.fakes.fake_{port_module} import {fake_class}")
            repo_deps.append(
                {
                    "fixture_name": fixture_name,
                    "fake_class": fake_class,
                    "param_name": param_name,
                }
            )

    # Build methods with TODO lines
    methods = []
    for m in methods_raw:
        method_name = m.get("name", "execute")
        todo_lines = test_todo("service", service_name, method_name, m, artifact_ref="YDK contract components")
        methods.append(
            {
                "name": method_name,
                "todo_lines": todo_lines,
            }
        )

    # If no methods defined, add a single execute stub
    if not methods:
        methods.append(
            {
                "name": "execute",
                "todo_lines": test_todo("service", service_name, artifact_ref="YDK contract components"),
            }
        )

    return {
        "name": base_name,
        "snake_name": to_snake(base_name),
        "fake_imports": fake_imports,
        "repo_port_imports": repo_port_imports,
        "dependencies": repo_deps,
        "methods": methods,
        "has_not_found_error": any(
            e if isinstance(e, str) else e.get("name", "")
            for m in methods_raw
            for e in m.get("errors", [])
            if (e if isinstance(e, str) else e.get("name", "")).endswith("NotFoundError")
        ),
    }


def main() -> None:
    uc_path = os.environ.get("YDK_COMPONENTS_CONTRACT", "")
    dm_path = os.environ.get("YDK_COMPONENTS_ENTITY", "")

    if not uc_path or not Path(uc_path).exists():
        print("[]")
        return

    uc_data = yaml.safe_load(Path(uc_path).read_text(encoding="utf-8")) or {}

    # Load entity names so we can match RepositoryPort deps
    entity_names: set[str] = set()
    if dm_path and Path(dm_path).exists():
        dm_data = yaml.safe_load(Path(dm_path).read_text(encoding="utf-8")) or {}
        entity_list = dm_data if isinstance(dm_data, list) else dm_data.get("entities", [])
        entity_names = {derive_name(e) for e in entity_list if isinstance(e, dict)}

    # Set up Jinja2
    templates_dir = Path(__file__).parent.parent / "templates" / "tests"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("service_unit_test.py.j2")

    output = []
    for uc in uc_data if isinstance(uc_data, list) else []:
        context = build_service_context(uc, entity_names)
        content = template.render(**context).rstrip() + "\n"
        snake = to_snake(context["name"] + "Service")
        output.append({"path": f"tests/unit/core/services/test_{snake}.py", "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

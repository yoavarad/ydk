#!/usr/bin/env python3
"""
Generator: unit-test-bodies
Generate service unit test bodies from test-plan.yaml scenarios.
Falls back to stubs when test-plan.yaml is absent or a method has no scenarios.

Input: test-plan.yaml (YDK_COMPONENTS_TEST_PLAN), YDK contract components
Output: tests/unit/core/services/test_{service_snake}_service.py per service
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _context.naming import derive_name, to_snake

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_yaml(path: str) -> dict:
    if path and Path(path).exists():
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {}


def _use_cases_path() -> str:
    """Resolve services artifact path."""
    val = os.environ.get("YDK_COMPONENTS_CONTRACT", "")
    if val and Path(val).exists():
        return val
    return ""


def _service_snake(service_name: str) -> str:
    """'ProjectService' → 'project_service'"""
    return to_snake(service_name)


def _entity_from_service(service_name: str) -> str:
    """'ProjectService' → 'Project'"""
    if service_name.endswith("Service"):
        return service_name[: -len("Service")]
    return service_name


def _repo_entity_from_port(port_name: str) -> str | None:
    if port_name.endswith("RepositoryPort"):
        return port_name[: -len("RepositoryPort")]
    return None


def _build_repo_deps(uc: dict) -> list[dict]:
    """Collect RepositoryPort deps from a use-case entry."""
    deps = []
    for port_entry in uc.get("ports", []):
        port = port_entry["name"] if isinstance(port_entry, dict) else port_entry
        entity = _repo_entity_from_port(port)
        if entity:
            snake_entity = to_snake(entity)
            deps.append(
                {
                    "fixture_name": f"fake_{snake_entity}_repo",
                    "fake_class": f"Fake{entity}Repository",
                    "fake_import": f"from tests.fakes.fake_{snake_entity}_repository import Fake{entity}Repository",
                    "param_name": to_snake(port),  # e.g. project_repository_port
                }
            )
    return deps


# ---------------------------------------------------------------------------
# Per-service file builder
# ---------------------------------------------------------------------------


def _render_method_stub(service_name: str, method_name: str, entity_snake: str) -> str:
    """Single test stub when no test-plan scenario covers this method."""
    return (
        f"    def test_{method_name}(self, service: {service_name}) -> None:\n"
        f"        # TODO[ydk:test:{service_name}.{method_name}@YDK contract components]\n"
        f"        raise NotImplementedError\n"
    )


def _render_scenario(
    service_name: str,
    method_name: str,
    scenario: dict,
    entity_snake: str,
) -> str:
    sid = scenario.get("id", "unnamed")
    arrange = scenario.get("arrange", "")
    act = scenario.get("act", "")
    assert_str = scenario.get("assert", "")
    entity_pascal = "".join(w.capitalize() for w in entity_snake.split("_"))
    fake_class = f"Fake{entity_pascal}Repository"

    lines = [
        f"    def test_{method_name}_{sid}("
        f"self, service: {service_name}, fake_{entity_snake}_repo: {fake_class}) -> None:",
        f"        # Arrange: {arrange}",
        f"        # Act: {act}",
        f"        # TODO[ydk:test:{service_name}.{method_name}@test-plan.yaml]",
        f"        # IMPLEMENT: {assert_str}",
        "        raise NotImplementedError",
    ]
    return "\n".join(lines) + "\n"


def _render_error_scenario(
    service_name: str,
    method_name: str,
    error: dict,
    entity_snake: str,
) -> str:
    error_name = error.get("name", "UnknownError")
    arrange = error.get("arrange", "")
    act = error.get("act", "")
    assert_str = error.get("assert", f"raises {error_name}")
    sid = to_snake(error_name)
    entity_pascal = "".join(w.capitalize() for w in entity_snake.split("_"))
    fake_class = f"Fake{entity_pascal}Repository"

    lines = [
        f"    def test_{method_name}_raises_{sid}("
        f"self, service: {service_name}, fake_{entity_snake}_repo: {fake_class}) -> None:",
        f"        # Arrange: {arrange}",
        f"        # Act: {act}",
        f"        # TODO[ydk:test:{service_name}.{method_name}_error@test-plan.yaml]",
        f"        # IMPLEMENT: {assert_str}",
        "        raise NotImplementedError",
    ]
    return "\n".join(lines) + "\n"


def build_service_file(
    service_name: str,
    uc: dict,
    plan_entries: list[dict],  # list of {method, scenarios, errors} from test-plan
) -> str:
    entity = _entity_from_service(service_name)
    entity_snake = to_snake(entity)
    snake_svc = _service_snake(service_name)
    deps = _build_repo_deps(uc)

    # Gather all methods from use-case
    methods_raw = uc.get("methods", {})
    if isinstance(methods_raw, dict):
        method_names = list(methods_raw.keys())
    else:
        method_names = [m.get("name", "execute") for m in methods_raw]
    if not method_names:
        method_names = ["execute"]

    # Index plan entries by method name
    plan_by_method: dict[str, dict] = {}
    for entry in plan_entries:
        m = entry.get("method", "")
        if m:
            plan_by_method[m] = entry

    # Collect unique fake imports — sorted alphabetically for ruff I001
    fake_imports = [dep["fake_import"] for dep in deps]
    # Deduplicate and sort
    unique_fake_imports = sorted(set(fake_imports))

    # ---- Header ----
    lines: list[str] = [
        f'"""Unit tests for {service_name}. Uses fakes — no DB or external services."""',
        "from __future__ import annotations",
        "",
        "import pytest",
        "",
        f"from app.core.services.{snake_svc} import {service_name}",
    ]
    for imp in unique_fake_imports:
        lines.append(imp)
    lines.append("")
    lines.append("")

    # ---- Fixtures ----
    fixture_names = []
    for dep in deps:
        fixture_names.append(dep["fixture_name"])
        lines.append("@pytest.fixture")
        lines.append(f"def {dep['fixture_name']}() -> {dep['fake_class']}:")
        lines.append(f"    return {dep['fake_class']}()")
        lines.append("")
        lines.append("")

    # service fixture
    if deps:
        params = ", ".join(f"{dep['fixture_name']}: {dep['fake_class']}" for dep in deps)
        kwargs = ", ".join(f"{dep['param_name']}={dep['fixture_name']}" for dep in deps)
        lines.append("@pytest.fixture")
        lines.append(f"def service({params}) -> {service_name}:")
        lines.append(f"    return {service_name}({kwargs})")
    else:
        lines.append("@pytest.fixture")
        lines.append(f"def service() -> {service_name}:")
        lines.append(f"    return {service_name}()")
    lines.append("")
    lines.append("")

    # ---- Test class ----
    lines.append(f"class Test{service_name}:")
    lines.append(f"    # Generated from test-plan.yaml → unit_tests → {service_name}")

    test_methods_written = False
    for method_name in method_names:
        plan_entry = plan_by_method.get(method_name)
        if plan_entry:
            scenarios = plan_entry.get("scenarios", [])
            errors = plan_entry.get("errors", [])
            if scenarios or errors:
                lines.append("")
                lines.append(f"    # --- {service_name}.{method_name} ---")
            for scenario in scenarios:
                lines.append("")
                lines.append(_render_scenario(service_name, method_name, scenario, entity_snake).rstrip())
                test_methods_written = True
            for error in errors:
                lines.append("")
                lines.append(_render_error_scenario(service_name, method_name, error, entity_snake).rstrip())
                test_methods_written = True

            # If plan entry exists but has no scenarios/errors, fall back to stub
            if not scenarios and not errors:
                lines.append("")
                lines.append(_render_method_stub(service_name, method_name, entity_snake).rstrip())
                test_methods_written = True
        else:
            # No plan entry for this method — generate a stub
            lines.append("")
            lines.append(_render_method_stub(service_name, method_name, entity_snake).rstrip())
            test_methods_written = True

    if not test_methods_written:
        lines.append("")
        lines.append(f"    def test_placeholder(self, service: {service_name}) -> None:")
        lines.append(f"        # TODO[ydk:test:{service_name}@test-plan.yaml]")
        lines.append("        raise NotImplementedError")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    test_plan_path = os.environ.get("YDK_COMPONENTS_TEST_PLAN", "")
    uc_path = _use_cases_path()

    if not uc_path:
        print("[]")
        return

    uc_data = _load_yaml(uc_path)
    plan_data = _load_yaml(test_plan_path)

    # Index plan unit_tests by service name, then collect per-method entries
    plan_by_service: dict[str, list[dict]] = {}
    for entry in plan_data.get("unit_tests", []):
        svc = entry.get("service", "")
        if svc:
            plan_by_service.setdefault(svc, []).append(entry)

    output = []
    for uc in uc_data if isinstance(uc_data, list) else []:
        service_name = derive_name(uc)
        if not service_name.endswith("Service"):
            service_name = f"{service_name}Service"

        plan_entries = plan_by_service.get(service_name, [])
        content = build_service_file(service_name, uc, plan_entries)

        snake_svc = _service_snake(service_name)
        output.append({"path": f"test_{snake_svc}.py", "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

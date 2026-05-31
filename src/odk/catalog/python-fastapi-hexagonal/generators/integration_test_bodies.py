#!/usr/bin/env python3
"""
Generator: integration-test-bodies
Generate integration test bodies from test-plan.yaml scenarios.
Falls back to basic stubs (based on response status codes from ODK route components)
when test-plan.yaml is absent.

Input: test-plan.yaml (ODK_COMPONENTS_TEST_PLAN), ODK route components (ODK_COMPONENTS_ROUTE)
Output: tests/integration/api/test_{domain}_routes.py per domain
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_yaml(path: str) -> dict:
    if path and Path(path).exists():
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {}


def _endpoint_to_domain(path: str) -> str:
    segments = [p for p in path.split("/") if p and not p.startswith("{")]
    if segments and segments[0] == "api":
        segments = segments[1:]
    raw = segments[0] if segments else "root"
    return re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_") or "root"


def _endpoint_key(method: str, path: str) -> str:
    """Normalise to e.g. 'GET /projects' for matching against test-plan entries."""
    return f"{method.upper()} {path}"


def _path_to_func(method: str, path: str) -> str:
    clean = re.sub(r"\{[^}]+\}", "by_id", path)
    clean = clean.replace("/", "_").replace("-", "_")
    clean = re.sub(r"_+", "_", clean).strip("_")
    return f"{method.lower()}_{clean}" if clean else f"{method.lower()}_root"


def _scenario_id_to_func(scenario_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", scenario_id.lower()).strip("_")


def _status_codes_from_contract(ep: dict) -> list[int]:
    codes = []
    for r in ep.get("responses", []):
        if "status" in r:
            codes.append(r["status"])
    return codes


# ---------------------------------------------------------------------------
# File builders
# ---------------------------------------------------------------------------

FILE_HEADER_TMPL = """\
\"\"\"Integration tests for {domain} routes using FastAPI TestClient.\"\"\"
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.middleware.auth import get_current_user
from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {{"sub": "test-user"}}
    return TestClient(app)


@pytest.fixture
def unauth_client() -> TestClient:
    return TestClient(create_app())


class Test{class_name}Routes:
"""


def _render_test_with_scenario(
    domain: str,
    endpoint_key: str,
    scenario: dict,
    method: str,
    path: str,
) -> str:
    sid = _scenario_id_to_func(scenario.get("id", "scenario"))
    ep_prefix = _path_to_func(method, path)
    func_name = f"{ep_prefix}_{sid}"
    description = scenario.get("assert", "")
    auth = scenario.get("auth", "valid_token")
    fixture = "unauth_client" if auth == "none" else "client"
    arrange = scenario.get("arrange", "")

    lines = [
        f"    def test_{func_name}(self, {fixture}: TestClient) -> None:",
    ]
    if arrange:
        lines.append(f"        # Arrange: {arrange}")
    lines.append(f"        # TODO[odk:test:integration:{endpoint_key}@test-plan.yaml]")
    lines.append(f"        # IMPLEMENT: {description}")
    lines.append("        raise NotImplementedError")
    return "\n".join(lines) + "\n"


def _render_test_stub_from_contract(
    method: str,
    path: str,
    status_codes: list[int],
) -> str:
    func_name = _path_to_func(method, path)
    status_str = ", ".join(str(c) for c in status_codes) if status_codes else "?"
    lines = [
        f"    def test_{func_name}(self, client: TestClient) -> None:",
        f"        # TODO[odk:test:integration:{method} {path}@ODK route components]",
        f"        # IMPLEMENT: test this endpoint — known status codes: {status_str}",
        "        raise NotImplementedError",
    ]
    return "\n".join(lines) + "\n"


def build_domain_file(
    domain: str,
    contract_endpoints: list[dict],
    plan_entries: list[dict],  # integration_tests entries matching this domain
) -> str:
    class_name = "".join(w.capitalize() for w in domain.split("_"))

    # Index plan entries by endpoint key
    plan_by_endpoint: dict[str, list[dict]] = {}
    for entry in plan_entries:
        key = entry.get("endpoint", "")
        if key:
            plan_by_endpoint.setdefault(key, []).append(entry)

    header = FILE_HEADER_TMPL.format(domain=domain, class_name=class_name)
    body_lines: list[str] = []

    # For each contract endpoint in this domain, generate tests
    # Use test-plan scenarios if available, else fall back to stubs
    for ep in contract_endpoints:
        method = ep.get("method", "GET")
        path = ep.get("path", "/")
        key = f"{method.upper()} {path}"

        # Try exact match first, then normalised (e.g. without braces)
        plan_scenarios: list[dict] = []
        for k, entries in plan_by_endpoint.items():
            # Normalise for matching: replace path params
            normalised_plan = re.sub(r"\{[^}]+\}", "{id}", k)
            normalised_contract = re.sub(r"\{[^}]+\}", "{id}", key)
            if normalised_plan == normalised_contract:
                for entry in entries:
                    plan_scenarios.extend(entry.get("scenarios", []))

        body_lines.append(f"    # {key}")
        if plan_scenarios:
            for scenario in plan_scenarios:
                body_lines.append("")
                body_lines.append(_render_test_with_scenario(domain, key, scenario, method, path).rstrip())
        else:
            # Fallback stub with status codes from contract
            codes = _status_codes_from_contract(ep)
            body_lines.append("")
            body_lines.append(_render_test_stub_from_contract(method, path, codes).rstrip())

        body_lines.append("")

    if not body_lines:
        body_lines.append("    def test_placeholder(self, client: TestClient) -> None:")
        body_lines.append(f"        # TODO[odk:test:integration:{domain}@ODK route components]")
        body_lines.append("        raise NotImplementedError")

    return header + "\n".join(body_lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    test_plan_path = os.environ.get("ODK_COMPONENTS_TEST_PLAN", "")
    contracts_path = os.environ.get("ODK_COMPONENTS_ROUTE", "")

    if not contracts_path or not Path(contracts_path).exists():
        print("[]")
        return

    contracts_data = _load_yaml(contracts_path)
    plan_data = _load_yaml(test_plan_path)

    # Group contract endpoints by domain
    domain_endpoints: dict[str, list[dict]] = {}
    for ep in contracts_data if isinstance(contracts_data, list) else []:
        domain = _endpoint_to_domain(ep.get("path", ""))
        domain_endpoints.setdefault(domain, []).append(ep)

    # Index plan integration_tests by domain (derived from endpoint path)
    plan_by_domain: dict[str, list[dict]] = {}
    for entry in plan_data.get("integration_tests", []):
        endpoint_str = entry.get("endpoint", "")
        # Extract path from e.g. "GET /projects"
        parts = endpoint_str.split(" ", 1)
        path = parts[1] if len(parts) == 2 else endpoint_str
        domain = _endpoint_to_domain(path)
        plan_by_domain.setdefault(domain, []).append(entry)

    output = []
    for domain, endpoints in domain_endpoints.items():
        plan_entries = plan_by_domain.get(domain, [])
        content = build_domain_file(domain, endpoints, plan_entries)
        output.append({"path": f"test_{domain}_routes.py", "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

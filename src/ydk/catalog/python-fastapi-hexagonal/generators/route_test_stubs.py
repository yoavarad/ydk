#!/usr/bin/env python3
"""
Generator: route-test-stubs
Generate integration tests for each route domain using FastAPI TestClient.
Tests are generated with @pytest.mark.xfail markers linked to TODO IDs.
Input: YDK route components
Output: tests/integration/api/test_{domain}_routes.py per domain
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Add generators dir to path for _context imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def path_to_func(method: str, path: str) -> str:
    """Generate a valid Python function name from HTTP method + path."""
    clean = re.sub(r"\{[^}]+\}", "by_id", path)
    clean = clean.replace("/", "_").replace("-", "_")
    clean = re.sub(r"_+", "_", clean).strip("_")
    return f"{method.lower()}_{clean}" if clean else f"{method.lower()}_root"


def _default_status_for_method(method: str) -> int:
    """Return the expected HTTP status code for a given method."""
    return {"POST": 201, "DELETE": 204}.get(method.upper(), 200)


def _build_request_body(ep: dict) -> str:
    """Build a JSON-serializable request body dict from endpoint request fields."""
    request = ep.get("request", {})
    if not request or not isinstance(request, dict):
        return "{}"

    body: dict = {}
    for field_name, field_def in request.items():
        if isinstance(field_def, dict):
            field_type = field_def.get("type", "string")
            if field_type == "string":
                body[field_name] = f"Test {field_name.replace('_', ' ').title()}"
            elif field_type in ("int", "integer", "number"):
                body[field_name] = 1
            elif field_type == "boolean":
                body[field_name] = True
            elif field_type == "array":
                body[field_name] = []
            else:
                body[field_name] = f"test-{field_name}"
        else:
            body[field_name] = f"test-{field_name}"

    return repr(body)


def _extract_response_fields(ep: dict) -> list[str]:
    """Extract field names from endpoint response schema."""
    responses = ep.get("responses", {})
    if not responses or not isinstance(responses, dict):
        return []

    fields: list[str] = []
    # Look for the success response
    for key, resp in responses.items():
        if isinstance(resp, dict):
            schema = resp.get("schema", resp.get("fields", {}))
            if isinstance(schema, dict):
                fields.extend(schema.keys())
            break
    return fields


def _generate_todo_id(domain: str, func_name: str) -> str:
    """Generate a deterministic TODO ID for xfail linking."""
    # Use a hash-like approach for stable IDs
    combined = f"{domain}.{func_name}"
    # Simple numeric hash for TODO numbering
    num = abs(hash(combined)) % 9000 + 1000
    return f"YDK-TODO-{num:04d}"


def build_domain_context(tag: str, endpoints: list) -> dict:
    """Build the Jinja2 template context for one route test file."""
    routes = []
    post_endpoints = []
    get_endpoints = []

    for ep in endpoints:
        method = ep.get("method", "GET")
        path = ep.get("path", "/")

        # Strip /api prefix for function name generation
        func_path = path
        if func_path.startswith("/api/"):
            func_path = func_path[4:]
        elif func_path.startswith("/api"):
            func_path = func_path[4:] or "/"

        # Strip tag prefix
        tag_prefix = f"/{tag}"
        if func_path.startswith(tag_prefix):
            func_path = func_path[len(tag_prefix) :] or "/"

        func_name = path_to_func(method, func_path)
        todo_id = _generate_todo_id(tag, func_name)

        # Determine expected status
        response = ep.get("response", {})
        if isinstance(response, dict) and "status" in response:
            expected_status = response["status"]
        else:
            expected_status = _default_status_for_method(method)

        # Build request body for methods that need one
        request_body = "{}"
        if method.upper() in ("POST", "PUT", "PATCH"):
            request_body = _build_request_body(ep)

        # Extract response fields for assertions
        response_fields = _extract_response_fields(ep)

        # Derive xfail reason linked to TODO
        service_name = "".join(w.capitalize() for w in tag.split("_")) + "Service"
        method_label = func_name.split("_", 1)[-1] if "_" in func_name else func_name
        xfail_reason = f"{todo_id}: implement {service_name}.{method_label}"

        route_entry = {
            "func_name": func_name,
            "method": method,
            "path": path,
            "request_body": request_body,
            "expected_status": expected_status,
            "response_fields": response_fields,
            "xfail_reason": xfail_reason,
            "todo_id": todo_id,
        }
        routes.append(route_entry)

        # Track for round-trip detection
        if method.upper() == "POST":
            post_endpoints.append((path, route_entry))
        elif method.upper() == "GET" and "{" in path:
            get_endpoints.append((path, route_entry))

    # Build round-trip tests: match POST /resources with GET /resources/{id}
    roundtrip_tests = []
    for post_path, post_entry in post_endpoints:
        # Look for a matching GET path with a parameter
        for get_path, get_entry in get_endpoints:
            # /api/strategies matches /api/strategies/{id}
            base_post = post_path.rstrip("/")
            base_get = re.sub(r"/\{[^}]+\}$", "", get_path)
            if base_post == base_get:
                # Build the f-string path for GET
                get_path_template = re.sub(r"\{([^}]+)\}", r'{data["id"]}', get_path)
                roundtrip_func = post_entry["func_name"].replace("post_", "create_")
                todo_id = _generate_todo_id(tag, f"roundtrip_{roundtrip_func}")
                service_name = "".join(w.capitalize() for w in tag.split("_")) + "Service"
                roundtrip_tests.append(
                    {
                        "func_name": roundtrip_func,
                        "create_path": post_path,
                        "get_path_template": get_path_template,
                        "request_body": post_entry["request_body"],
                        "create_status": post_entry["expected_status"],
                        "xfail_reason": f"{todo_id}: implement {service_name} create + get roundtrip",
                    }
                )
                break

    return {
        "tag": tag,
        "routes": routes,
        "roundtrip_tests": roundtrip_tests,
    }


def main() -> None:
    contracts_path = os.environ.get("YDK_COMPONENTS_ROUTE", "")
    if not contracts_path or not Path(contracts_path).exists():
        print("[]")
        return

    data = yaml.safe_load(Path(contracts_path).read_text(encoding="utf-8")) or {}

    # Set up Jinja2
    templates_dir = Path(__file__).parent.parent / "templates" / "tests"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("route_test.py.j2")

    # Group endpoints by first meaningful path segment (domain)
    groups: dict[str, list] = {}
    for ep in data if isinstance(data, list) else []:
        segments = [p for p in ep.get("path", "").split("/") if p and not p.startswith("{")]
        if segments and segments[0] == "api":
            segments = segments[1:]
        raw_domain = segments[0] if segments else "root"
        domain = re.sub(r"[^a-z0-9]+", "_", raw_domain.lower()).strip("_") or "root"
        groups.setdefault(domain, []).append(ep)

    output = []
    for domain, endpoints in groups.items():
        context = build_domain_context(domain, endpoints)
        content = template.render(**context).rstrip() + "\n"
        output.append({"path": f"tests/integration/api/test_{domain}_routes.py", "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Generator: schema-tests
Generate Pydantic schema validation tests from ODK route components + data-model.yaml.
Input: ODK route components, data-model.yaml
Output: tests/unit/api/schemas/test_{domain}_schemas.py per domain
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
from _context.naming import derive_name, iter_fields, to_snake
from jinja2 import Environment, FileSystemLoader, StrictUndefined

# Default test values per canonical type
_TEST_VALUES: dict[str, str] = {
    "str": "test-value",
    "int": "1",
    "float": "1.0",
    "bool": "True",
    "uuid": "00000000-0000-0000-0000-000000000001",
    "datetime": "2024-01-01T00:00:00Z",
    "date": "2024-01-01",
    "json": "{}",
    "bytes": "b''",
}


def _to_camel(s: str) -> str:
    return "".join(w.capitalize() for w in re.split(r"[_\-/]", s) if w)


def _schema_names_from_endpoint(ep: dict) -> list[str]:
    """Derive the schema class names that pydantic_schemas.py would generate."""
    names = []
    method = ep.get("method", "GET").upper()
    service = ep.get("service", "")
    path = ep.get("path", "")
    segments = [p for p in path.strip("/").split("/") if p and p != "api" and not p.startswith("{")]
    tag = segments[0] if segments else "common"

    suffix_map = {"POST": "Create", "PUT": "Update", "PATCH": "Update"}
    body = ep.get("body") or ep.get("request", {}).get("body", {})

    if method in ("POST", "PUT", "PATCH"):
        if isinstance(body, dict) and body.get("fields"):
            schema_name = _to_camel(service or tag) + suffix_map.get(method, "Request")
            names.append(schema_name)
        elif isinstance(body, str):
            # String ref — pydantic_schemas resolves entity and appends suffix
            base = body
            for s in ("Create", "Update", "Response", "Schema", "Request", "Patch"):
                if base.endswith(s):
                    base = base[: -len(s)]
                    break
            schema_name = base + suffix_map.get(method, "Request")
            names.append(schema_name)

    response = ep.get("response", "")
    if isinstance(response, dict):
        response = response.get("entity", response.get("schema_name", ""))
    if isinstance(response, str) and response:
        # Skip MIME types and non-identifier strings (e.g. "text/event-stream")
        if re.match(r"^[A-Za-z][A-Za-z0-9_]*$", response):
            base = response.removesuffix("Response") if response.endswith("Response") else response
            if base:
                names.append(base + "Response")

    return names


def _collect_entity_fields(entity_name: str, entities_by_name: dict) -> list[dict]:
    """Return fields for a matching entity, or empty list."""
    entity = entities_by_name.get(entity_name)
    if entity:
        return [{"name": fname, **fdef} for fname, fdef in iter_fields(entity)]
    return []


def _schema_context(schema_name: str, entities_by_name: dict) -> dict:
    """
    Build a minimal schema test context.
    Infer entity from schema name by stripping common suffixes.
    """
    # Strip suffixes like Request, Response, Create, Update, List
    base = re.sub(r"(Request|Response|Create|Update|List|Schema)$", "", schema_name)
    fields = _collect_entity_fields(base, entities_by_name)
    # Try singular form (e.g. "Projects" -> "Project", "Tasks" -> "Task")
    if not fields and base.endswith("s"):
        fields = _collect_entity_fields(base[:-1], entities_by_name)

    required_fields = []
    defaults = []

    for f in fields:
        is_optional = f.get("type", "").lower().startswith("optional[")
        has_default = "default" in f
        is_pk = f.get("primary_key", False)

        if is_pk:
            continue  # PK usually auto-set

        if not is_optional and not has_default:
            ftype = f.get("type", "str").lower()
            test_val = _TEST_VALUES.get(ftype, "test-value")
            required_fields.append({"name": f["name"], "test_value": test_val})
        elif has_default:
            raw_default = f["default"]
            if isinstance(raw_default, bool):
                expected = str(raw_default)
            elif raw_default == "now":
                # skip — dynamic default, not useful to assert a specific value
                continue
            elif isinstance(raw_default, str):
                # String defaults map to server_default in SQLAlchemy — not in Pydantic Create schema
                # Only include if this is a Response/Update schema where the field might appear
                if schema_name.endswith("Create") or schema_name.endswith("Request"):
                    continue
                expected = f'"{raw_default}"'
            else:
                expected = str(raw_default)
            defaults.append({"name": f["name"], "expected": expected})

    return {
        "name": schema_name,
        "required_fields": required_fields,
        "defaults": defaults,
    }


def build_domain_context(domain: str, schema_names: list[str], entities_by_name: dict) -> dict:
    """Build the Jinja2 template context for one schema test file."""
    # De-duplicate while preserving order
    seen: set[str] = set()
    unique_names = []
    for n in schema_names:
        if n not in seen:
            seen.add(n)
            unique_names.append(n)

    schemas = [_schema_context(n, entities_by_name) for n in unique_names]
    # Only include schemas that have something testable
    schemas = [s for s in schemas if s["required_fields"] or s["defaults"]]
    # Only import schema classes that actually have tests
    tested_names = [s["name"] for s in schemas]

    imports = [f"from app.api.schemas.{to_snake(domain)} import {', '.join(tested_names)}"] if tested_names else []

    return {
        "domain": domain,
        "imports": imports,
        "schemas": schemas,
    }


def main() -> None:
    contracts_path = os.environ.get("ODK_COMPONENTS_ROUTE", "")
    dm_path = os.environ.get("ODK_COMPONENTS_ENTITY", "")

    if not contracts_path or not Path(contracts_path).exists():
        print("[]")
        return

    data = yaml.safe_load(Path(contracts_path).read_text(encoding="utf-8")) or {}

    # Load entity fields by name for inferring required fields
    entities_by_name: dict[str, dict] = {}
    if dm_path and Path(dm_path).exists():
        dm_data = yaml.safe_load(Path(dm_path).read_text(encoding="utf-8")) or {}
        for entity in dm_data if isinstance(dm_data, list) else []:
            entities_by_name[derive_name(entity)] = entity

    # Set up Jinja2
    templates_dir = Path(__file__).parent.parent / "templates" / "tests"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("schema_test.py.j2")

    # Group schema names by domain (first non-api path segment)
    domain_schemas: dict[str, list[str]] = {}
    for ep in data if isinstance(data, list) else []:
        segments = [p for p in ep.get("path", "").split("/") if p and not p.startswith("{")]
        if segments and segments[0] == "api":
            segments = segments[1:]
        raw_domain = segments[0] if segments else "root"
        domain = re.sub(r"[^a-z0-9]+", "_", raw_domain.lower()).strip("_") or "root"
        schema_names = _schema_names_from_endpoint(ep)
        domain_schemas.setdefault(domain, []).extend(schema_names)

    output = []
    for domain, schema_names in domain_schemas.items():
        context = build_domain_context(domain, schema_names, entities_by_name)
        if not context["schemas"]:
            # Still emit the file but with minimal content (import-only)
            pass
        content = template.render(**context).rstrip() + "\n"
        output.append({"path": f"test_{domain}_schemas.py", "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

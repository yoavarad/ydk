#!/usr/bin/env python3
"""
Generator: pydantic-schemas
Generates Pydantic BaseModel request/response schemas from ODK route components.
Groups endpoints by domain (first path segment after /api/).
Handles both dict body definitions and string schema name references.
Input: ODK route components, data-model.yaml
Output: app/api/schemas/{domain}.py per API domain group
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

# Add generators dir to path for _context imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _context.naming import derive_name, iter_fields, to_snake
from _context.types import CANONICAL_TO_PYDANTIC
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def _pluralize(word: str) -> str:
    try:
        import inflect

        p = inflect.engine()
        return p.plural(word) or word + "s"
    except ImportError:
        if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
            return word[:-1] + "ies"
        return word + "s"


def _singularize(word: str) -> str:
    """Singularize a word."""
    try:
        import inflect

        p = inflect.engine()
        singular = p.singular_noun(word)
        return singular if singular else word
    except ImportError:
        if word.endswith("ies") and len(word) > 3:
            return word[:-3] + "y"
        if word.endswith("es") and not word.endswith("ses"):
            return word[:-2]
        if word.endswith("s") and not word.endswith("ss"):
            return word[:-1]
        return word


def snake(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "_", s.lower()).strip("_")


def camel(s: str) -> str:
    return "".join(w.capitalize() for w in re.split(r"[_\-/]", s) if w)


def py_type(t: str) -> str:
    return CANONICAL_TO_PYDANTIC.get(t.lower(), "Any")


def _find_entity_for_ref(ref: str, entities: dict) -> str | None:
    """Given a string ref like 'StrategyCreate', find the matching entity name."""
    # Try exact match first
    if ref in entities:
        return ref
    # Strip common suffixes and try to match entity name
    for suffix in ("Create", "Update", "Response", "Schema", "Request", "Patch"):
        if ref.endswith(suffix):
            base = ref[: -len(suffix)]
            if base in entities:
                return base
    return None


def _schema_name_from_use_case(maps_to: str, method: str) -> str | None:
    """Derive a unique schema name from maps_to_use_case, e.g. 'TaskService.complete_task' -> 'CompleteTaskRequest'.

    Returns None if maps_to is empty or doesn't contain a dot.
    """
    if not maps_to or "." not in maps_to:
        return None
    method_name = maps_to.split(".", 1)[1]
    return camel(method_name) + "Request"


def _fields_from_service_method(
    maps_to: str, services: dict, *, exclude_path_params: list[str] | None = None
) -> list[dict] | None:
    """Look up method input params in services dict and return schema fields.

    Excludes path params (e.g. 'project_id') and common non-body params like 'user_id'.
    Returns None if the service/method is not found or has no body-eligible params.
    """
    if not maps_to or "." not in maps_to:
        return None
    svc_name, method_name = maps_to.split(".", 1)
    svc = services.get(svc_name)
    if not svc:
        return None
    methods = svc.get("methods", {})
    # ODK map format: {method_name: {params: ..., returns: ...}}
    if isinstance(methods, dict):
        m = methods.get(method_name)
        if not m:
            return None
        input_params = m.get("input") or m.get("params", {})
        if not input_params:
            return None
    else:
        # Legacy list format
        m = None
        for item in methods:
            if item.get("name") == method_name:
                m = item
                break
        if not m:
            return None
        input_params = m.get("input", {})
        if not input_params:
            return None
    # Normalize input format: may be a flat dict {name: type} or {fields: [{name, type}]}
    if isinstance(input_params, dict) and "fields" in input_params:
        param_pairs = [(f["name"], f["type"]) for f in input_params["fields"]]
    elif isinstance(input_params, dict):
        param_pairs = list(input_params.items())
    else:
        return None
    exclude = {"user_id"}  # injected by auth, not from request body
    if exclude_path_params:
        exclude.update(exclude_path_params)
    fields = []
    for pname, ptype in param_pairs:
        if pname in exclude:
            continue
        ptype_str = str(ptype)
        ftype = py_type(ptype_str)
        is_optional = ptype_str.lower().startswith("optional[")
        if is_optional:
            fields.append({"name": pname, "py_type": f"{ftype} | None", "default": "None"})
        else:
            fields.append({"name": pname, "py_type": ftype, "default": None})
    return fields if fields else None
    return None


def _extract_path_params(ep: dict) -> list[str]:
    """Extract path parameter names from an endpoint definition."""
    params = []
    # From request.path_params
    request_obj = ep.get("request", {}) or {}
    if isinstance(request_obj, dict):
        for p in request_obj.get("path_params", []):
            params.append(p.get("name", ""))
    # From URL pattern {param}
    path = ep.get("path", "")
    params.extend(re.findall(r"\{(\w+)\}", path))
    return list(set(p for p in params if p))


def build_domain_context(domain: str, endpoints: list, entities: dict, services: dict | None = None) -> dict:
    """Build the Jinja2 template context for one domain group."""
    imports: set[str] = set()
    schemas = []
    seen_schemas = set()
    services = services or {}

    for ep in endpoints:
        method = ep.get("method", "GET")
        service = ep.get("service", "")
        maps_to = ep.get("maps_to_use_case", "")

        # Request schema
        request_obj = ep.get("request", {}) or {}
        body = ep.get("body") or request_obj.get("body", {})

        # Inline request schema: request: {schema: Name, fields: [...]}
        req_schema_name = request_obj.get("schema") if isinstance(request_obj, dict) else None
        req_inline_fields = request_obj.get("fields") if isinstance(request_obj, dict) else None
        if req_schema_name and req_inline_fields and req_schema_name not in seen_schemas:
            fields = []
            for f in req_inline_fields:
                fname = f.get("name", "")
                ftype = py_type(f.get("type", "str"))
                required = f.get("required", True)
                if required:
                    fields.append({"name": fname, "py_type": ftype, "default": None})
                else:
                    fields.append({"name": fname, "py_type": f"{ftype} | None", "default": "None"})
            if fields:
                schemas.append({"name": req_schema_name, "fields": fields, "from_attributes": False})
                seen_schemas.add(req_schema_name)

        if method in ("POST", "PUT", "PATCH"):
            # Normalize body: dict-of-dicts → {fields: [{name:, type:, required:}]}
            if isinstance(body, dict) and "fields" not in body and body:
                # Check if it looks like a field map (values are dicts with 'type')
                if all(isinstance(v, dict) and "type" in v for v in body.values()):
                    body = {"fields": [{"name": k, **v} for k, v in body.items()]}
            if isinstance(body, dict) and "fields" in body:
                # Derive a unique schema name per endpoint from maps_to_use_case when available.
                # Fall back to the singular entity name for the domain.
                use_case_name = _schema_name_from_use_case(maps_to, method)
                # Use singular form for schema name (StrategyCreate, not StrategiesCreate)
                entity_label = service or _singularize(domain)
                # For sub-resource POST actions (e.g. /strategies/{id}/clone),
                # derive schema name from the action verb
                path = ep.get("path", "")
                path_segments = [s for s in path.strip("/").split("/") if s and not s.startswith("{") and s != "api"]
                is_sub_action = (
                    method == "POST"
                    and len(path_segments) > 1
                    and any(s.startswith("{") for s in path.strip("/").split("/"))
                )
                if is_sub_action and path_segments:
                    # Last non-param segment is the action: /strategies/{id}/clone → "clone"
                    action = path_segments[-1]
                    domain_name = camel(action) + camel(entity_label) + "Request"
                else:
                    domain_name = camel(entity_label) + {
                        "POST": "Create",
                        "PUT": "Update",
                        "PATCH": "Update",
                    }.get(method, "Request")
                schema_name = use_case_name if use_case_name else domain_name
                # If the use-case name collides, fall back to domain name; if both collide, skip
                if schema_name in seen_schemas:
                    schema_name = domain_name if schema_name != domain_name else schema_name
                if schema_name not in seen_schemas:
                    fields = []
                    for f in body.get("fields", []):
                        fname = f.get("name", "")
                        ftype = py_type(f.get("type", "str"))
                        required = f.get("required", True)
                        if required:
                            fields.append({"name": fname, "py_type": ftype, "default": None})
                        else:
                            fields.append({"name": fname, "py_type": f"{ftype} | None", "default": "None"})
                    if fields:
                        schemas.append({"name": schema_name, "fields": fields, "from_attributes": False})
                        seen_schemas.add(schema_name)
            elif isinstance(body, str):
                # String ref like "StrategyCreate" — resolve to entity
                entity_name = _find_entity_for_ref(body, entities)
                if entity_name:
                    entity = entities[entity_name]
                    suffix = {"POST": "Create", "PUT": "Update", "PATCH": "Update"}.get(method, "Request")
                    schema_name = entity_name + suffix
                    if schema_name not in seen_schemas:
                        fields = []
                        for fname, fdef in iter_fields(entity):
                            if fdef.get("primary_key"):
                                continue  # Skip PK for create/update
                            if fname in ("created_at", "updated_at"):
                                continue  # Skip timestamps for create/update
                            ftype = py_type(fdef.get("type", "string"))
                            required = fdef.get("required", True)
                            if method == "PUT" or method == "PATCH":
                                # All fields optional for update
                                opt_type = f"{ftype} | None"
                                fields.append({"name": fname, "py_type": opt_type, "default": "None"})
                            elif required:
                                fields.append({"name": fname, "py_type": ftype, "default": None})
                            else:
                                fields.append({"name": fname, "py_type": f"{ftype} | None", "default": "None"})
                        if fields:
                            schemas.append({"name": schema_name, "fields": fields, "from_attributes": False})
                            seen_schemas.add(schema_name)
            elif maps_to and services:
                # No inline body — derive schema from services.yaml method signature
                path_params = _extract_path_params(ep)
                svc_fields = _fields_from_service_method(maps_to, services, exclude_path_params=path_params)
                if svc_fields:
                    schema_name = _schema_name_from_use_case(maps_to, method)
                    if schema_name and schema_name not in seen_schemas:
                        schemas.append({"name": schema_name, "fields": svc_fields, "from_attributes": False})
                        seen_schemas.add(schema_name)

        # Response schema — only generate if entity "belongs" to this domain
        # e.g., TaskResponse belongs in tasks.py, not projects.py

        # Inline response schema: response: {name: SomeName, fields: [...]}
        response_raw = ep.get("response", "")
        if isinstance(response_raw, dict) and "fields" in response_raw:
            schema_name = response_raw.get("name", "")
            if schema_name and schema_name not in seen_schemas:
                fields = []
                for f in response_raw.get("fields", []):
                    fname = f.get("name", "")
                    ftype = py_type(f.get("type", "str"))
                    required = f.get("required", True)
                    if required:
                        fields.append({"name": fname, "py_type": ftype, "default": None})
                    else:
                        fields.append({"name": fname, "py_type": f"{ftype} | None", "default": "None"})
                if fields:
                    # All *Response schemas need from_attributes=True so FastAPI can validate
                    # ORM objects returned by services directly against the Pydantic schema.
                    is_response = schema_name.endswith("Response")
                    schemas.append({"name": schema_name, "fields": fields, "from_attributes": is_response})
                    seen_schemas.add(schema_name)

        response = ep.get("response", "")
        if isinstance(response, dict):
            response = response.get("entity", response.get("schema_name", ""))
        # Normalize: "StrategyResponse" → "Strategy", "Strategy" → "Strategy"
        if isinstance(response, str) and response:
            response = response.removesuffix("Response") if response.endswith("Response") else response
        # Skip MIME types like "text/event-stream" — not a Python class name
        if isinstance(response, str) and not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", response):
            continue
        if isinstance(response, str) and response in entities:
            # Skip cross-domain responses — they'll be generated in their own domain file
            # Entity "Project" → domain "projects" (plural), "Task" → "tasks", etc.
            entity_snake = to_snake(response)
            domain_singular = _singularize(domain)
            entity_matches_domain = (
                entity_snake == domain
                or _pluralize(entity_snake) == domain  # strategy→strategies, status→statuses
                or entity_snake + "s" == domain  # simple fallback
                or entity_snake + "es" == domain
                or entity_snake.startswith(domain)  # backtest_run→backtest
                or entity_snake.startswith(domain_singular + "_")  # strategy_run→strategies
            )
            if not entity_matches_domain:
                continue
            schema_name = response + "Response"
            if schema_name not in seen_schemas:
                entity = entities[response]
                fields = []
                for fname, fdef in iter_fields(entity):
                    ftype = py_type(fdef.get("type", "string"))
                    required = fdef.get("required", True)
                    if required:
                        fields.append({"name": fname, "py_type": ftype, "default": None})
                    else:
                        fields.append({"name": fname, "py_type": f"{ftype} | None", "default": "None"})
                if fields:
                    schemas.append({"name": schema_name, "fields": fields, "from_attributes": True})
                    seen_schemas.add(schema_name)

    # Generate Response schemas for entities that match this domain but weren't already generated.
    # This handles both: (a) routes using responses:{200:{shape:...}} instead of response: EntityName
    # and (b) sub-resource entities (e.g. StrategyRun in the "strategies" domain).
    for entity_name, entity in entities.items():
        entity_snake = to_snake(entity_name)
        domain_singular = _singularize(domain)
        entity_matches_domain = (
            entity_snake == domain
            or _pluralize(entity_snake) == domain
            or entity_snake + "s" == domain
            or entity_snake + "es" == domain
            or entity_snake.startswith(domain)
            or entity_snake.startswith(domain_singular + "_")  # strategy_run→strategies
        )
        if entity_matches_domain:
            schema_name = entity_name + "Response"
            if schema_name not in seen_schemas:
                fields = []
                for fname, fdef in iter_fields(entity):
                    ftype = py_type(fdef.get("type", "string"))
                    required = fdef.get("required", True)
                    if required:
                        fields.append({"name": fname, "py_type": ftype, "default": None})
                    else:
                        fields.append({"name": fname, "py_type": f"{ftype} | None", "default": "None"})
                if fields:
                    schemas.append({"name": schema_name, "fields": fields, "from_attributes": True})
                    seen_schemas.add(schema_name)

    # Always import just BaseModel — model_config uses dict literal, not ConfigDict
    imports.add("from pydantic import BaseModel")

    # Dynamically add imports based on used types
    all_field_types = {f["py_type"] for s in schemas for f in s.get("fields", [])}
    if any("datetime" in t for t in all_field_types):
        imports.add("from datetime import datetime")
    if any("date" in t and "datetime" not in t for t in all_field_types):
        imports.add("from datetime import date")
    if any("UUID" in t for t in all_field_types):
        imports.add("from uuid import UUID")
    if any("Decimal" in t for t in all_field_types):
        imports.add("from decimal import Decimal")
    if any("Any" in t for t in all_field_types):
        imports.add("from typing import Any")

    # Group imports: stdlib → third-party (pydantic) → first-party
    _third_party = ("pydantic",)
    stdlib_imps = sorted(i for i in imports if not any(i.startswith(f"from {p}") for p in _third_party))
    third_imps = sorted(i for i in imports if any(i.startswith(f"from {p}") for p in _third_party))
    grouped_imports: list[str] = []
    if stdlib_imps:
        grouped_imports.extend(stdlib_imps)
    if stdlib_imps and third_imps:
        grouped_imports.append("")
    grouped_imports.extend(third_imps)

    return {
        "imports": grouped_imports,
        "schemas": schemas,
    }


def main() -> None:
    contracts_path = os.environ.get("ODK_COMPONENTS_ROUTE", "")
    datamodel_path = os.environ.get("ODK_COMPONENTS_ENTITY", "")
    services_path = os.environ.get("ODK_COMPONENTS_CONTRACT", "")
    if not contracts_path or not Path(contracts_path).exists():
        print("[]")
        return

    raw_contracts = yaml.safe_load(Path(contracts_path).read_text())
    contracts = raw_contracts if isinstance(raw_contracts, list) else []
    entities = {}
    if datamodel_path and Path(datamodel_path).exists():
        raw_entities = yaml.safe_load(Path(datamodel_path).read_text())
        entity_list = raw_entities if isinstance(raw_entities, list) else []
        entities = {derive_name(e): e for e in entity_list}

    # Load contracts indexed by name for per-endpoint schema derivation
    services: dict[str, dict] = {}
    if services_path and Path(services_path).exists():
        raw_services = yaml.safe_load(Path(services_path).read_text())
        svc_list = raw_services if isinstance(raw_services, list) else []
        for svc in svc_list:
            services[derive_name(svc)] = svc

    # Set up Jinja2
    templates_dir = Path(__file__).parent.parent / "templates" / "schemas"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("schema.py.j2")

    # Group by domain
    by_domain: dict[str, list] = defaultdict(list)
    for ep in contracts:
        path = ep.get("path", "")
        parts = [p for p in path.strip("/").split("/") if p and p != "api"]
        raw_domain = parts[0] if parts else "common"
        domain = re.sub(r"[^a-z0-9]+", "_", raw_domain.lower()).strip("_") or "common"
        by_domain[domain].append(ep)

    output = []
    # List of (module_snake, [class_name, ...]) for explicit __init__.py imports
    schema_exports: list[tuple[str, list[str]]] = []

    domains_with_schemas: set[str] = set()
    for domain, endpoints in by_domain.items():
        context = build_domain_context(domain, endpoints, entities, services)
        if context["schemas"]:
            content = template.render(**context).rstrip() + "\n"
            module = snake(domain)
            output.append({"path": f"app/api/schemas/{module}.py", "content": content})
            class_names = [s["name"] for s in context["schemas"]]
            schema_exports.append((module, class_names))
            domains_with_schemas.add(domain)

    # For domains without schemas OR without a Response class, ensure a Response exists
    # so route imports don't fail (routes always infer XResponse from tag)
    existing_response_names: set[str] = set()
    for _mod, names in schema_exports:
        for name in names:
            if name.endswith("Response"):
                existing_response_names.add(name)

    for domain in by_domain:
        module = snake(domain)
        singular = _singularize(domain)
        response_name = camel(singular) + "Response"

        if response_name in existing_response_names:
            continue

        if domain not in domains_with_schemas:
            # No schema file at all — create stub
            stub_content = (
                "from pydantic import BaseModel\n\n\n"
                f"class {response_name}(BaseModel):\n"
                f'    """Generic response for {domain} domain."""\n\n'
                '    model_config = {"from_attributes": True}\n'
            )
            output.append({"path": f"app/api/schemas/{module}.py", "content": stub_content})
            schema_exports.append((module, [response_name]))
        else:
            # Schema file exists but lacks Response class — append to existing file
            # Find the existing output entry and append
            for entry in output:
                if entry["path"] == f"app/api/schemas/{module}.py":
                    entry["content"] += (
                        f"\n\nclass {response_name}(BaseModel):\n"
                        f'    """Generic response for {domain} domain."""\n\n'
                        '    model_config = {"from_attributes": True}\n'
                    )
                    # Update schema_exports
                    for i, (m, names) in enumerate(schema_exports):
                        if m == module:
                            schema_exports[i] = (m, names + [response_name])
                            break
                    break

    # Generate __init__.py with explicit re-exports (X as X), one per line — deduplicated
    # Collect all (module, name) pairs, then sort globally by (module, name) for ruff I001.
    if schema_exports:
        all_exports: list[tuple[str, str]] = []
        seen_names: set[str] = set()
        for module, class_names in schema_exports:
            for name in sorted(class_names):
                if name not in seen_names:
                    all_exports.append((module, name))
                    seen_names.add(name)
        all_exports.sort(key=lambda t: (t[0], t[1]))
        init_lines = [f"from app.api.schemas.{module} import {name} as {name}" for module, name in all_exports]
        output.append({"path": "app/api/schemas/__init__.py", "content": "\n".join(init_lines) + "\n"})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

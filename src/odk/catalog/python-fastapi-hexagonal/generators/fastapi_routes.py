#!/usr/bin/env python3
"""
Generator: fastapi-routes
Generate full thin FastAPI route handlers delegating to services via Depends().
Input: ODK route components, services.yaml
Output: app/api/routes/{tag}.py per API group
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
from _context.naming import derive_name, to_snake
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def to_camel(name: str) -> str:
    return "".join(w.capitalize() for w in re.split(r"[_\-/]", name) if w)


def path_to_func(method: str, path: str) -> str:
    """Generate a valid Python function name from HTTP method + path."""
    clean = re.sub(r"\{[^}]+\}", "by_id", path)
    clean = clean.replace("/", "_").replace("-", "_")
    clean = re.sub(r"_+", "_", clean).strip("_")
    return f"{method.lower()}_{clean}" if clean else f"{method.lower()}_root"


def _pluralize(word: str) -> str:
    """Pluralize a snake_case word using the inflect library for correctness."""
    try:
        import inflect

        _p = inflect.engine()
        plural = _p.plural(word)
        return plural if plural else word + "s"
    except ImportError:
        # Fallback for environments without inflect
        if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
            return word[:-1] + "ies"
        if word.endswith(("s", "x", "z", "ch", "sh")):
            return word + "es"
        return word + "s"


def _route_sort_key(ep: dict) -> tuple:
    path = ep.get("path", "")
    segments = [s for s in path.split("/") if s]
    param_count = sum(1 for s in segments if s.startswith("{"))
    return (param_count, path)


def _service_method_name(ep: dict) -> str:
    uc = ep.get("maps_to_use_case", "") or ep.get("maps_to", "")
    if uc and "." in uc:
        return uc.split(".")[-1]
    method = ep.get("method", "GET").upper()
    path = ep.get("path", "")
    method_map = {
        "GET": "list",
        "POST": "create",
        "PUT": "update",
        "PATCH": "update",
        "DELETE": "delete",
    }
    base = method_map.get(method, method.lower())
    segments = [s for s in path.strip("/").split("/") if s]
    has_id_param = any(s.startswith("{") for s in segments)
    if method == "GET" and has_id_param:
        # Check if there's a sub-resource after the id param (e.g. /strategies/{id}/runs)
        after_id = []
        found_id = False
        for s in segments:
            if found_id and not s.startswith("{"):
                after_id.append(s)
            if s.startswith("{"):
                found_id = True
        if after_id:
            # Sub-resource GET: /strategies/{id}/runs → list_runs
            base = "list_" + "_".join(s.replace("-", "_") for s in after_id)
        else:
            base = "get"
    elif method == "POST" and has_id_param:
        # Sub-resource POST: /strategies/{id}/clone → clone
        after_id = []
        found_id = False
        for s in segments:
            if found_id and not s.startswith("{"):
                after_id.append(s)
            if s.startswith("{"):
                found_id = True
        if after_id:
            base = "_".join(s.replace("-", "_") for s in after_id)
    return base


def _build_entity_domain_map() -> dict[str, str]:
    """Pre-compute which api-contracts domain generates each entity's response schema.
    Returns {entity_base: domain_name} based on which domain has the most endpoints
    returning that entity.
    """
    ac_path = os.environ.get("ODK_COMPONENTS_ROUTE", "")
    if not ac_path or not Path(ac_path).exists():
        return {}
    data = yaml.safe_load(Path(ac_path).read_text(encoding="utf-8")) or {}
    counts: dict[str, dict[str, int]] = {}
    for ep in data if isinstance(data, list) else []:
        resp = ep.get("response", "")
        if isinstance(resp, dict):
            resp = resp.get("entity", resp.get("name", ""))
        if not isinstance(resp, str) or not resp or "/" in resp:
            continue
        entity_base = resp.removesuffix("Response") if resp.endswith("Response") else resp
        segments = [p for p in ep.get("path", "").strip("/").split("/") if p and p != "api" and not p.startswith("{")]
        if not segments:
            continue
        domain = re.sub(r"[^a-z0-9]+", "_", segments[0].lower()).strip("_") or "root"
        counts.setdefault(entity_base, {})[domain] = counts.get(entity_base, {}).get(domain, 0) + 1
    return {entity: max(domains, key=lambda d: domains[d]) for entity, domains in counts.items()}


# Module-level cache
_ENTITY_DOMAIN_MAP: dict[str, str] | None = None


def _get_entity_domain_map() -> dict[str, str]:
    global _ENTITY_DOMAIN_MAP
    if _ENTITY_DOMAIN_MAP is None:
        _ENTITY_DOMAIN_MAP = _build_entity_domain_map()
    return _ENTITY_DOMAIN_MAP


def _load_use_cases() -> dict:
    """Load ODK contract components and index methods by ServiceName.method_name."""
    uc_path = os.environ.get("ODK_COMPONENTS_CONTRACT", "")
    if not uc_path or not Path(uc_path).exists():
        return {}
    data = yaml.safe_load(Path(uc_path).read_text(encoding="utf-8")) or {}
    contracts = data if isinstance(data, list) else []
    index: dict[str, dict] = {}
    for uc in contracts:
        svc_name = derive_name(uc)
        methods = uc.get("methods", {})
        if isinstance(methods, dict):
            # ODK map format: {method_name: {params: ..., returns: ...}}
            for method_name, method_def in methods.items():
                key = f"{svc_name}.{method_name}"
                # Normalize to legacy format for downstream compat
                m = {"name": method_name, **(method_def if isinstance(method_def, dict) else {})}
                # Map ODK 'params' to legacy 'input' format
                if "params" in m and "input" not in m:
                    m["input"] = m["params"]
                index[key] = m
        elif isinstance(methods, list):
            # Legacy list format
            for m in methods:
                key = f"{svc_name}.{m['name']}"
                index[key] = m
    return index


# Module-level cache for use-cases index
_USE_CASES_INDEX: dict | None = None


def _get_use_cases_index() -> dict:
    global _USE_CASES_INDEX
    if _USE_CASES_INDEX is None:
        _USE_CASES_INDEX = _load_use_cases()
    return _USE_CASES_INDEX


TYPE_MAP = {
    "str": "str",
    "string": "str",
    "int": "int",
    "integer": "int",
    "bigint": "int",
    "float": "float",
    "bool": "bool",
    "boolean": "bool",
    "uuid": "UUID",
    "datetime": "datetime",
    "date": "date",
    "decimal": "Decimal",
    "text": "str",
    "object": "dict",
    "json": "dict",
    "jsonb": "dict",
}


def _map_simple_type(t: str) -> str:
    """Map a canonical type to Python for route params."""
    t = t.strip()
    low = t.lower()
    if low.startswith("optional[") and low.endswith("]"):
        inner = _map_simple_type(t[9:-1])
        return f"{inner} | None"
    return TYPE_MAP.get(low, t)


def _singularize(word: str) -> str:
    """Singularize a snake_case word."""
    try:
        import inflect

        _p = inflect.engine()
        singular = _p.singular_noun(word)
        return singular if singular else word
    except ImportError:
        # Fallback heuristics
        if word.endswith("ies") and len(word) > 3:
            return word[:-3] + "y"
        if word.endswith("es") and not word.endswith("ses"):
            return word[:-2]
        if word.endswith("s") and not word.endswith("ss"):
            return word[:-1]
        return word


def _infer_service_name_from_tag(tag: str) -> str:
    """Infer a service class name from a route tag (e.g. 'strategies' -> 'StrategyService')."""
    singular = _singularize(tag.replace("_", " ").replace("-", " ").replace(" ", "_"))
    return to_camel(singular) + "Service"


def _get_path_param_types(ep: dict) -> dict[str, str]:
    """Extract path parameter types from request.path_params dict format.

    Handles: request: {path_params: {id: {type: integer, required: true}}}
    Returns: {param_name: canonical_type}
    """
    request_obj = ep.get("request", {}) or {}
    if not isinstance(request_obj, dict):
        return {}
    path_params = request_obj.get("path_params", {})
    if not isinstance(path_params, dict):
        return {}
    result: dict[str, str] = {}
    for param_name, param_def in path_params.items():
        if isinstance(param_def, dict):
            result[param_name] = param_def.get("type", "string")
        elif isinstance(param_def, str):
            result[param_name] = param_def
    return result


def _get_query_params(ep: dict) -> dict[str, dict]:
    """Extract query parameters from request.query dict format.

    Returns: {param_name: {type: ..., required: bool}}
    """
    request_obj = ep.get("request", {}) or {}
    if not isinstance(request_obj, dict):
        return {}
    query = request_obj.get("query", {})
    if not isinstance(query, dict):
        return {}
    return query


def _has_request_body(ep: dict) -> bool:
    """Check if endpoint has a request body (dict-of-dicts or fields list format)."""
    body_info = ep.get("body") or (ep.get("request", {}) or {}).get("body", {})
    if not body_info:
        return False
    if isinstance(body_info, str):
        return True
    if isinstance(body_info, dict):
        # dict-of-dicts format: {field_name: {type: ..., required: ...}}
        if "fields" in body_info:
            return True
        # Check if all values are dicts with 'type' key
        if body_info and all(isinstance(v, dict) and "type" in v for v in body_info.values()):
            return True
    return False


def _infer_response_entity(ep: dict, tag: str) -> str:
    """Infer response entity name from the endpoint's response shape or tag.

    For standard CRUD endpoints, returns the singular PascalCase entity name
    that the response schema should reference (e.g. 'Strategy' for tag 'strategies').
    For sub-resource endpoints (e.g. /strategies/{id}/runs), returns the sub-resource
    entity (e.g. 'StrategyRun') rather than the parent ('Strategy').
    """
    # Check explicit response field first (legacy format)
    response = ep.get("response", "")
    if isinstance(response, dict):
        entity = response.get("entity") or response.get("name") or response.get("schema_name", "")
        if entity:
            return entity.removesuffix("Response") if entity.endswith("Response") else entity
    elif isinstance(response, str) and response:
        return response.removesuffix("Response") if response.endswith("Response") else response

    # Check for sub-resource list pattern: GET /tag/{id}/sub_resource returning an array
    http_method = ep.get("method", "GET").upper()
    if http_method == "GET":
        path = ep.get("path", "")
        segments = [s for s in path.strip("/").split("/") if s and s != "api"]
        # Find sub-resource segments after an ID param
        after_id: list[str] = []
        found_id = False
        for s in segments:
            if found_id and not s.startswith("{"):
                after_id.append(s)
            if s.startswith("{"):
                found_id = True
        if after_id:
            # Only infer sub-resource entity when endpoint returns an array (list response)
            # This avoids mis-inferring for detail endpoints like /webhooks/{id}/info
            responses = ep.get("responses", {})
            is_array_response = False
            if isinstance(responses, dict):
                success_resp = responses.get(200) or responses.get("200")
                if isinstance(success_resp, dict):
                    shape = success_resp.get("shape", {})
                    if isinstance(shape, dict) and shape.get("type") == "array":
                        is_array_response = True
            # Also treat as list sub-resource if the last segment is a plural noun
            # (runs, events, fills, positions, etc.)
            last_seg = after_id[-1].replace("-", "_")
            is_plural_endpoint = last_seg.endswith("s") and last_seg != "status"
            if is_array_response or is_plural_endpoint:
                # Sub-resource: combine parent singular + all sub-resource singulars
                # /strategies/{id}/runs → StrategyRun
                # /strategies/{id}/runs/{run_id}/events → StrategyRunEvent
                parent_singular = _singularize(tag)
                parts = [to_camel(parent_singular)]
                for seg in after_id:
                    parts.append(to_camel(_singularize(seg.replace("-", "_"))))
                return "".join(parts)

    # For new format: check responses.{status}.shape to see if it looks like a single entity
    # Standard CRUD operations return the entity shape — infer from tag
    http_method = ep.get("method", "GET").upper()
    responses = ep.get("responses", {})
    if isinstance(responses, dict):
        # GET by id, POST, PATCH — return single entity
        success_status = "201" if http_method == "POST" else "200"
        success_resp = responses.get(int(success_status)) or responses.get(success_status)
        if success_resp and isinstance(success_resp, dict):
            shape = success_resp.get("shape", {})
            if isinstance(shape, dict):
                # If shape has 'type: array', this is a list endpoint — still return entity
                if shape.get("type") == "array":
                    # List endpoint — entity response wraps items
                    pass
                elif shape:
                    # Single entity shape — good, entity maps to tag
                    pass

    # Infer from tag: 'strategies' -> 'Strategy'
    singular = _singularize(tag)
    return to_camel(singular)


def build_router_context(tag: str, endpoints: list) -> dict:
    """Build the Jinja2 template context for one router file."""
    endpoints = sorted(endpoints, key=_route_sort_key)

    # Collect service names needed — infer from tag if no explicit maps_to_use_case
    service_names = set()
    has_any_use_case = False
    for ep in endpoints:
        uc_name = ep.get("maps_to_use_case", "") or ep.get("maps_to", "")
        if uc_name:
            has_any_use_case = True
            svc = uc_name.split(".")[0] if "." in uc_name else uc_name
            service_name = svc if svc.endswith("Service") else f"{svc}Service"
            service_names.add(service_name)

    # If no explicit use-case mapping found, infer service from tag
    if not has_any_use_case:
        inferred_service = _infer_service_name_from_tag(tag)
        service_names.add(inferred_service)

    schema_domain = to_snake(tag).replace("-", "_")

    dep_names = sorted(f"{sname}Dep" for sname in service_names)
    if dep_names:
        service_imports = [f"from app.api.dependencies import {', '.join(dep_names)}"]
    else:
        service_imports = []

    routes = []
    for ep in endpoints:
        method = ep["method"]
        path = ep["path"]

        # Strip /api prefix
        if path.startswith("/api/"):
            path = path[4:]
        elif path.startswith("/api"):
            path = path[4:] or "/"

        # Strip the tag prefix since router already has prefix=/{tag}
        tag_prefix = f"/{tag}"
        if path.startswith(tag_prefix):
            path = path[len(tag_prefix) :] or "/"

        use_case = ep.get("maps_to_use_case", "") or ep.get("maps_to", "")
        svc_base = use_case.split(".")[0] if "." in use_case else use_case
        if svc_base:
            service_name = svc_base if svc_base.endswith("Service") else f"{svc_base}Service"
        elif not has_any_use_case:
            # Infer service from tag when no explicit use-case mapping exists
            service_name = _infer_service_name_from_tag(tag)
        else:
            service_name = None
        func_name = path_to_func(ep["method"], path)
        svc_method = _service_method_name(ep)

        # Path params from URL template
        path_params = re.findall(r"\{(\w+)\}", path)
        param_parts: list[str] = []
        http_method = ep["method"].upper()

        # Get path param types from request.path_params (new ODK format)
        declared_path_param_types = _get_path_param_types(ep)

        # Look up use-case inputs to get types and identify query params
        uc_inputs: dict[str, str] = {}  # name -> canonical type
        if use_case and service_name:
            uc_index = _get_use_cases_index()
            uc_method = uc_index.get(use_case, {})
            raw_inp = uc_method.get("input") or uc_method.get("args") or {}
            if isinstance(raw_inp, dict) and "fields" in raw_inp:
                # input: {fields: [{name: ..., type: ...}]} shorthand format
                uc_inputs = {item["name"]: item.get("type", "str") for item in raw_inp["fields"] if "name" in item}
            elif isinstance(raw_inp, dict):
                uc_inputs = {k: str(v) for k, v in raw_inp.items()}
            elif isinstance(raw_inp, list):
                uc_inputs = {item["name"]: item.get("type", "str") for item in raw_inp if "name" in item}

        # Map path params to use-case input names.
        # e.g. path {id} may correspond to use-case input project_id.
        # Build: path_param_mapping[path_name] = uc_input_name
        path_param_mapping: dict[str, str] = {}  # path_param -> uc_input_name
        claimed_uc_inputs: set[str] = set()
        for pp in path_params:
            if pp in uc_inputs:
                # Exact match: path param name == uc input name
                path_param_mapping[pp] = pp
                claimed_uc_inputs.add(pp)
            else:
                # Fuzzy match: path param "id" matches uc input "project_id" (ends with _id)
                # Filter already-claimed inputs to avoid duplicate matches
                candidates = [k for k in uc_inputs if (k.endswith(f"_{pp}") or k == pp) and k not in claimed_uc_inputs]
                if len(candidates) == 1:
                    path_param_mapping[pp] = candidates[0]
                    claimed_uc_inputs.add(candidates[0])
                else:
                    path_param_mapping[pp] = pp  # no mapping found, use as-is

        # Type path params: prefer declared types from request.path_params,
        # then use-case types, then fallback to str
        for pp in path_params:
            if pp in declared_path_param_types:
                py_type = _map_simple_type(declared_path_param_types[pp])
            else:
                uc_name = path_param_mapping.get(pp, pp)
                if uc_name in uc_inputs:
                    py_type = _map_simple_type(uc_inputs[uc_name])
                else:
                    py_type = "str"
            param_parts.append(f"{pp}: {py_type}")

        # Extra params: use-case inputs that are NOT claimed by path params.
        # Also include query params declared in request.query for endpoints without use-case.
        query_params: list[dict] = []
        method_has_body = _has_request_body(ep) and http_method in ("POST", "PUT", "PATCH")

        if http_method == "GET" or http_method == "DELETE" or not method_has_body:
            # First, add use-case derived query params
            for inp_name, inp_type in uc_inputs.items():
                if inp_name in claimed_uc_inputs:
                    continue
                py_type = _map_simple_type(inp_type)
                is_optional = "| None" in py_type
                query_params.append({"name": inp_name, "type": py_type, "optional": is_optional})

            # Then, add declared query params from request.query (new format)
            declared_query = _get_query_params(ep)
            for qp_name, qp_def in declared_query.items():
                # Skip if already covered by use-case inputs
                if any(q["name"] == qp_name for q in query_params):
                    continue
                qp_type = qp_def.get("type", "string") if isinstance(qp_def, dict) else "string"
                qp_required = qp_def.get("required", False) if isinstance(qp_def, dict) else False
                py_type = _map_simple_type(qp_type)
                is_optional = not qp_required
                if is_optional and "| None" not in py_type:
                    py_type = f"{py_type} | None"
                query_params.append({"name": qp_name, "type": py_type, "optional": is_optional})

        for qp in query_params:
            if qp["optional"]:
                param_parts.append(f"{qp['name']}: {qp['type']} = None")
            else:
                param_parts.append(f"{qp['name']}: {qp['type']}")

        # Body param
        has_body = method_has_body

        if has_body:
            # Match schema naming from pydantic_schemas generator:
            # When maps_to_use_case is set (e.g. "TaskService.complete_task"),
            # schema name is CamelCase(method_name) + "Request" (e.g. "CompleteTaskRequest").
            # Otherwise fall back to Domain + Create/Update.
            schema_class = None
            if use_case and "." in use_case:
                method_name = use_case.split(".", 1)[1]
                schema_class = to_camel(method_name) + "Request"
            if not schema_class:
                service_label = ep.get("service", "")
                entity_label = service_label or _singularize(tag)
                # For sub-resource POST actions (e.g. /strategies/{id}/clone),
                # use action-based naming to match pydantic_schemas generator
                orig_path = ep.get("path", "")
                orig_segments = [
                    s for s in orig_path.strip("/").split("/") if s and not s.startswith("{") and s != "api"
                ]
                is_sub_action = (
                    http_method == "POST"
                    and len(orig_segments) > 1
                    and any(s.startswith("{") for s in orig_path.strip("/").split("/"))
                )
                if is_sub_action and orig_segments:
                    action = orig_segments[-1]
                    schema_class = to_camel(action) + to_camel(entity_label) + "Request"
                else:
                    schema_suffix = {"POST": "Create", "PUT": "Update", "PATCH": "Update"}.get(http_method, "Request")
                    schema_class = to_camel(entity_label) + schema_suffix
            param_parts.append(f"body: schemas.{schema_class}")

        # Service dependency
        if service_name:
            dep_name = f"{service_name}Dep"
            param_parts.append(f"service: {dep_name}")

        # Sort: params without defaults first, then params with defaults
        param_parts.sort(key=lambda p: " = " in p or "= " in p)
        param_str = ", ".join(param_parts)

        # Status code
        responses = ep.get("responses", [])
        # Normalize dict-format responses {200: {...}, 404: {...}} to list format
        if isinstance(responses, dict):
            responses = [{"status": int(k), **v} for k, v in responses.items()]
        success_resp = next((r for r in responses if r.get("status", 0) < 300), None)
        status_code = success_resp.get("status", 200) if success_resp else 200
        if http_method == "POST":
            status_code = 201

        # Response model — detect cross-domain to use correct schema module alias
        response_entity = ep.get("response", "")
        if isinstance(response_entity, dict):
            # Support both {entity: X} and {name: XxxResponse, fields: [...]} formats
            response_entity = (
                response_entity.get("entity") or response_entity.get("name") or response_entity.get("schema_name", "")
            )
        if isinstance(response_entity, str) and response_entity:
            # Skip MIME types and non-identifier strings (e.g. "text/event-stream")
            if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", response_entity):
                response_entity = ""
        # If no explicit response entity, infer from tag for standard CRUD endpoints
        # Skip inference for DELETE (no response body) and when explicit response="" was set
        if not response_entity and http_method != "DELETE" and "response" not in ep:
            response_entity = _infer_response_entity(ep, tag)
        if isinstance(response_entity, str) and response_entity:
            # Normalize: strip existing Response suffix to avoid doubling
            entity_base = (
                response_entity.removesuffix("Response") if response_entity.endswith("Response") else response_entity
            )
            entity_snake = to_snake(entity_base)
            tag_singular = _singularize(tag)
            entity_matches_tag = (
                entity_snake == tag
                or entity_snake + "s" == tag
                or entity_snake + "es" == tag
                or tag.startswith(entity_snake)  # strategy → strategies
                or entity_snake.startswith(tag)  # backtest_run → backtest
                or entity_snake.startswith(tag_singular + "_")  # strategy_run → strategies (sub-resource)
            )
            if not entity_matches_tag:
                # Cross-domain: look up the actual domain that generates this entity's schema
                entity_map = _get_entity_domain_map()
                actual_domain = entity_map.get(entity_base, _pluralize(entity_snake))
                if actual_domain == tag:
                    # Inline schema belongs to this domain despite name mismatch — use local schemas alias
                    entity_matches_tag = True
                    response_model = f"schemas.{entity_base}Response"
                else:
                    alias_domain = actual_domain
                    response_model = f"{alias_domain}_schemas.{entity_base}Response"
            else:
                response_model = f"schemas.{entity_base}Response"
        else:
            response_model = ""

        # Service call expression
        is_stub = not service_name
        if service_name:
            if has_body:
                # Build call: explicit path params + body splat.
                # We always use **body.model_dump() for body fields because:
                # 1. Body schema field names may differ from service param names
                #    (e.g. body has "name" but service expects "new_name")
                # 2. ty cannot verify body.field_name access against the schema
                # Path params are passed explicitly to avoid them leaking into the splat.
                call_args = []
                for pp in path_params:
                    uc_name = path_param_mapping.get(pp, pp)
                    call_args.append(f"{uc_name}={pp}")
                call_args.append("**body.model_dump()")
                call = f"service.{svc_method}({', '.join(call_args)})"
            else:
                # Build service call args: map path params to uc input names + query params
                call_args = []
                for pp in path_params:
                    uc_name = path_param_mapping.get(pp, pp)
                    call_args.append(f"{uc_name}={pp}")
                for qp in query_params:
                    call_args.append(f"{qp['name']}={qp['name']}")
                if call_args:
                    call = f"service.{svc_method}({', '.join(call_args)})"
                else:
                    call = f"service.{svc_method}()"
        else:
            call = ""

        # Return type annotation mirrors response_model (already has schemas. prefix)
        if response_model:
            return_annotation = response_model
        else:
            return_annotation = "None"

        # Wrap response_model in list[] for list endpoints
        is_list_endpoint = svc_method == "list" or (svc_method.startswith("list_") and http_method == "GET")
        if is_list_endpoint and response_model:
            response_model = f"list[{response_model}]"
            return_annotation = f"list[{return_annotation}]"

        # Determine if we need try/except — when there's a 404 error response
        # or when service method is get/update (likely to raise on not-found)
        has_404 = False
        raw_responses = ep.get("responses", {})
        if isinstance(raw_responses, dict):
            has_404 = 404 in raw_responses or "404" in raw_responses
        elif isinstance(raw_responses, list):
            has_404 = any(r.get("status") == 404 for r in raw_responses)
        needs_try = bool(service_name) and (svc_method in ("get", "update") or has_404)

        routes.append(
            {
                "method": method.lower(),
                "path": path,
                "func_name": func_name,
                "param_str": param_str,
                "status_code": status_code,
                "response_model": response_model,
                "return_annotation": return_annotation,
                "service_call": call,
                "is_stub": is_stub,
                "is_delete": svc_method == "delete" and bool(service_name),
                "needs_try": needs_try,
            }
        )

    # Check if any route param string uses X | None (Python 3.10+ style)
    has_optional = any("| None" in r["param_str"] for r in routes)
    has_try_routes = any(r["needs_try"] for r in routes)
    # Only import domain schema module if at least one route actually uses schemas.*
    has_schema_usage = any(
        r.get("response_model")
        and "_schemas." not in r.get("response_model", "")
        or "schemas." in r.get("param_str", "")
        for r in routes
    )

    # Collect extra schema imports for cross-domain response models
    extra_schema_imports = []
    seen_extra = set()
    for route in routes:
        rm = route.get("response_model", "")
        if "_schemas." in rm:
            # e.g. "tasks_schemas.TaskResponse" → need "from app.api.schemas import tasks as tasks_schemas"
            alias = rm.split(".")[0]  # e.g. "tasks_schemas"
            domain_name = alias.removesuffix("_schemas")  # e.g. "tasks"
            if domain_name not in seen_extra:
                seen_extra.add(domain_name)
                extra_schema_imports.append(f"from app.api.schemas import {domain_name} as {alias}")

    return {
        "tag": tag,
        "schema_domain": schema_domain,
        "service_imports": service_imports,
        "extra_schema_imports": extra_schema_imports,
        "routes": routes,
        "has_optional": has_optional,
        "has_try_routes": has_try_routes,
        "has_schema_usage": has_schema_usage,
    }


def main() -> None:
    contracts_path = os.environ.get("ODK_COMPONENTS_ROUTE", "")
    if not contracts_path or not Path(contracts_path).exists():
        print("[]")
        return

    data = yaml.safe_load(Path(contracts_path).read_text(encoding="utf-8")) or {}
    # Set up Jinja2
    templates_dir = Path(__file__).parent.parent / "templates" / "routes"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("route_file.py.j2")

    # Group endpoints by first meaningful path segment
    groups: dict[str, list] = {}
    for ep in data if isinstance(data, list) else []:
        segments = [p for p in ep.get("path", "").split("/") if p and not p.startswith("{")]
        if segments and segments[0] == "api":
            segments = segments[1:]
        raw_tag = segments[0] if segments else "root"
        # Sanitize tag to a valid Python identifier (hyphens, slashes → underscores)
        tag = re.sub(r"[^a-z0-9]+", "_", raw_tag.lower()).strip("_") or "root"
        groups.setdefault(tag, []).append(ep)

    output = []
    all_tags = []
    for tag, endpoints in groups.items():
        context = build_router_context(tag, endpoints)
        content = template.render(**context).rstrip() + "\n"
        output.append({"path": f"app/api/routes/{tag}.py", "content": content})
        all_tags.append(tag)

    # Generate __init__.py that wires all domain routers into api_router
    if all_tags:
        init_lines = [
            "from fastapi import APIRouter",
            "",
        ]
        for t in sorted(all_tags):
            init_lines.append(f"from app.api.routes.{t} import router as {t}_router")
        init_lines.append("")
        init_lines.append("api_router = APIRouter()")
        for t in sorted(all_tags):
            init_lines.append(f"api_router.include_router({t}_router)")
        init_lines.append("")
        output.append({"path": "app/api/routes/__init__.py", "content": "\n".join(init_lines)})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

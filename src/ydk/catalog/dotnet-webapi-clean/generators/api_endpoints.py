#!/usr/bin/env python3
"""
Generator: api-endpoints
Generates thin ASP.NET Core Minimal API endpoint mappings that delegate to the
injected Application-layer I{Name}Service (see service_stubs.py) -- the same
thin-route-delegates-to-service style as python-fastapi-hexagonal's fastapi_routes.py.
Routes are grouped per tag; each group becomes a static {Tag}Endpoints class exposing
an ``IEndpointRouteBuilder.Map{Tag}Endpoints()`` extension method.

Input: YDK route components (optional -- an unset YDK_COMPONENTS_ROUTE means the
project has no route components, e.g. a zero-component baseline) + contract
components (used to resolve service methods, parameter names/types and nullable
returns; optional).
Output: Api/Endpoints/{Tag}Endpoints.cs per route tag, plus a
Api/Endpoints/GeneratedEndpoints.cs aggregate that always exists (even with zero
tags) so Program.cs can call app.MapGeneratedEndpoints() unconditionally.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Add generators dir to path for local helper imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _dotnet_common import contract_methods, map_type, pluralize, service_and_entity_name, to_camel_param, to_pascal
from jinja2 import Environment, FileSystemLoader, StrictUndefined

_PATH_PARAM_RE = re.compile(r"\{(\w+)((?::[^}]*)?)\}")
_VERSION_SEGMENT_RE = re.compile(r"v\d+", re.IGNORECASE)
_MAP_CALLS = {"GET": "MapGet", "POST": "MapPost", "PUT": "MapPut", "PATCH": "MapPatch", "DELETE": "MapDelete"}
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})
_CRUD_BASES = {"GET": "list", "POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}
_CRUD_METHODS = frozenset({*_CRUD_BASES.values(), "get"})


def _path_segments(path: str) -> list[str]:
    """Path segments without the ``api`` / ``vN`` prefix segments."""
    return [s for s in path.strip("/").split("/") if s and s.lower() != "api" and not _VERSION_SEGMENT_RE.fullmatch(s)]


def route_tag(ep: dict) -> str:
    """Explicit ``tag`` if set, else the first non-param path segment, else ``root``."""
    tag = ep.get("tag")
    if isinstance(tag, str) and tag.strip():
        return tag.strip()
    for segment in _path_segments(str(ep.get("path", ""))):
        if not segment.startswith("{"):
            return segment
    return "root"


def tag_class_prefix(tag: str) -> str:
    """PascalCase, identifier-safe form of a route tag (items -> Items, order-items -> OrderItems)."""
    pascal = to_pascal(re.sub(r"[^0-9A-Za-z_\-]+", "_", tag)) or "Root"
    return pascal if pascal[0].isalpha() else f"Api{pascal}"


def _singularize(word: str) -> str:
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith(("sses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def build_service_index(contracts: list[dict]) -> dict[str, dict]:
    """Index contracts as {ServiceName: {"entity": Name, "methods": {PascalMethod: method_ctx}}}."""
    index: dict[str, dict] = {}
    for contract in contracts:
        service_name, entity_name = service_and_entity_name(contract)
        index[service_name] = {
            "entity": entity_name,
            "methods": {m["name"]: m for m in contract_methods(contract)},
        }
    return index


def _method_base(ep: dict) -> str:
    """Conventional service-method base for a route without maps_to (list/get/create/update/delete/<action>)."""
    http_method = str(ep.get("method", "GET")).upper()
    segments = _path_segments(str(ep.get("path", "")))
    first_param = next((i for i, s in enumerate(segments) if s.startswith("{")), None)
    base = _CRUD_BASES.get(http_method, http_method.lower())
    if first_param is None:
        return base
    after_id = [s.replace("-", "_") for s in segments[first_param + 1 :] if not s.startswith("{")]
    if http_method == "GET":
        return f"list_{'_'.join(after_id)}" if after_id else "get"
    if http_method == "POST" and after_id:
        return "_".join(after_id)
    return base


def _infer_service(tag: str, index: dict[str, dict]) -> str:
    candidate = f"{to_pascal(_singularize(tag))}Service"
    if candidate in index or len(index) != 1:
        return candidate
    return next(iter(index))


def _infer_method(base: str, entity: str, methods: dict[str, dict]) -> str:
    pascal = to_pascal(base)
    conventional = (
        [f"{pascal}{pluralize(entity)}", f"{pascal}{entity}", pascal]
        if base == "list"
        else [
            f"{pascal}{entity}",
            pascal,
        ]
    )
    for name in conventional:
        if name in methods:
            return name
    prefixed = [m for m in methods if m.startswith(pascal)]
    if len(prefixed) == 1:
        return prefixed[0]
    return conventional[0] if base in _CRUD_METHODS else pascal


def resolve_target(ep: dict, tag: str, index: dict[str, dict]) -> tuple[str, str]:
    """Return (ServiceName, MethodName) a route delegates to."""
    explicit = str(ep.get("maps_to_use_case") or ep.get("maps_to") or "")
    service_part, _, method_part = explicit.partition(".")
    if service_part:
        service_name = to_pascal(service_part)
        if not service_name.endswith("Service"):
            service_name += "Service"
    else:
        service_name = _infer_service(tag, index)

    if method_part:
        return service_name, to_pascal(method_part)
    known = index.get(service_name)
    entity = known["entity"] if known else service_name.removesuffix("Service")
    methods = known["methods"] if known else {}
    return service_name, _infer_method(_method_base(ep), entity, methods)


def _field_type(field: dict, *, default_required: bool) -> str:
    """C# type for a declared param/body field; nullable unless required."""
    base = map_type(str(field.get("type", "string")))
    required = bool(field.get("required", default_required))
    if (not required or field.get("nullable")) and not base.endswith("?"):
        base += "?"
    return base


def _declared_fields(container: object, *, default_required: bool) -> dict[str, str]:
    """Normalize a declared params/body map to {camelName: csharp_type}."""
    if not isinstance(container, dict):
        return {}
    items: list[tuple[str, dict]] = []
    if isinstance(container.get("fields"), list):
        items = [(f["name"], f) for f in container["fields"] if isinstance(f, dict) and f.get("name")]
    else:
        for name, value in container.items():
            if isinstance(value, dict) and "type" in value:
                items.append((name, value))
            elif isinstance(value, str):
                items.append((name, {"type": value}))
    return {to_camel_param(name): _field_type(f, default_required=default_required) for name, f in items}


def _success_status(ep: dict, http_method: str) -> int:
    responses = ep.get("responses")
    codes: list[int] = []
    if isinstance(responses, dict):
        success = responses.get("success")
        if isinstance(success, dict) and str(success.get("status", "")).isdigit():
            return int(success["status"])
        codes = [int(k) for k in responses if str(k).isdigit() and int(k) < 300]
    elif isinstance(responses, list):
        codes = [int(r["status"]) for r in responses if isinstance(r, dict) and str(r.get("status", "")).isdigit()]
        codes = [c for c in codes if c < 300]
    if codes:
        return min(codes)
    return {"POST": 201, "DELETE": 204}.get(http_method, 200)


def _return_lines(status: int, *, is_void: bool, nullable: bool) -> list[str]:
    if status == 204:
        return ["return Results.NoContent();"]
    if is_void:
        return ["return Results.Ok();" if status == 200 else f"return Results.StatusCode({status});"]
    if status != 200:
        return [f"return Results.Json(result, statusCode: {status});"]
    if nullable:
        return ["return result is null ? Results.NotFound() : Results.Ok(result);"]
    return ["return Results.Ok(result);"]


def build_route_context(ep: dict, tag: str, index: dict[str, dict], record_names: set[str]) -> tuple[dict, dict | None]:
    """Build the template context for one route, plus its request-body record (or None)."""
    http_method = str(ep.get("method", "GET")).upper()
    service_name, method_name = resolve_target(ep, tag, index)
    info = index.get(service_name, {}).get("methods", {}).get(method_name)
    contract_params = None if info is None else info["params"]
    contract_types = {} if contract_params is None else {p["name"]: p["type"] for p in contract_params}
    body_eligible = http_method in _BODY_METHODS

    request_obj = ep.get("request") if isinstance(ep.get("request"), dict) else {}
    declared_path = _declared_fields(request_obj.get("path_params"), default_required=True)
    declared_query = _declared_fields(
        request_obj.get("query") or request_obj.get("query_params"), default_required=False
    )
    declared_body = (
        _declared_fields(ep.get("body") or request_obj.get("body"), default_required=True) if body_eligible else {}
    )

    # Path params: match each route param to a contract param (exact name, else unique suffix match).
    path_params: list[str] = []
    path_arg_by_target: dict[str, str] = {}
    unclaimed = list(contract_types)
    for match in _PATH_PARAM_RE.finditer(str(ep.get("path", "/"))):
        name = to_camel_param(match.group(1))
        target = name if name in unclaimed else None
        if target is None:
            suffix_matches = [n for n in unclaimed if n.lower().endswith(name.lower())]
            target = suffix_matches[0] if len(suffix_matches) == 1 else None
        if target:
            unclaimed.remove(target)
        path_arg_by_target[target or name] = name
        path_type = declared_path.get(name) or (contract_types[target] if target else None) or "string"
        path_params.append(f"{path_type} {name}")
    path = _PATH_PARAM_RE.sub(lambda m: "{" + to_camel_param(m.group(1)) + m.group(2) + "}", str(ep.get("path", "/")))

    body_fields = dict(declared_body)
    query_params: dict[str, str] = dict(declared_query)
    if contract_params is None:
        args = [*path_arg_by_target.values(), *(f"request.{to_pascal(n)}" for n in body_fields), *query_params]
    else:
        args = []
        matched_query: set[str] = set()
        for name, ctype in contract_types.items():
            if name in path_arg_by_target:
                args.append(path_arg_by_target[name])
            elif name in body_fields or (body_eligible and name not in query_params):
                body_fields[name] = ctype
                args.append(f"request.{to_pascal(name)}")
            else:
                query_params[name] = ctype
                matched_query.add(name)
                args.append(name)
        query_params = {n: t for n, t in query_params.items() if n in matched_query}

    record = None
    lambda_params = list(path_params)
    if body_fields:
        record_name = f"{method_name}Request"
        suffix = 2
        while record_name in record_names:
            record_name = f"{method_name}Request{suffix}"
            suffix += 1
        record_names.add(record_name)
        record = {"name": record_name, "fields": [{"name": to_pascal(n), "type": t} for n, t in body_fields.items()]}
        lambda_params.append(f"{record_name} request")
    lambda_params.extend(f"{t} {n}" for n, t in query_params.items())

    service_var = to_camel_param(service_name)
    lambda_params.append(f"I{service_name} {service_var}")

    status = _success_status(ep, http_method)
    is_void = bool(info and info["is_void"])
    nullable = bool(info and info["task_return"].endswith("?>"))
    route = {
        "map_call": _MAP_CALLS.get(http_method, "MapGet"),
        "path": path,
        "params": ", ".join(lambda_params),
        "invocation": f"{service_var}.{method_name}({', '.join(args)})",
        "returns_value": not is_void and status != 204,
        "return_lines": _return_lines(status, is_void=is_void, nullable=nullable),
    }
    return route, record


def _route_sort_key(ep: dict) -> tuple[int, str]:
    path = str(ep.get("path", ""))
    return sum(1 for s in path.split("/") if s.startswith("{")), path


def build_tag_context(tag: str, routes: list[dict], index: dict[str, dict]) -> dict:
    """Build the Jinja2 template context for one {Tag}Endpoints.cs file."""
    record_names: set[str] = set()
    route_contexts: list[dict] = []
    records: list[dict] = []
    for ep in sorted(routes, key=_route_sort_key):
        route, record = build_route_context(ep, tag, index, record_names)
        route_contexts.append(route)
        if record:
            records.append(record)
    return {"tag": tag_class_prefix(tag), "records": records, "routes": route_contexts}


def _load_yaml_list(path: str) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def main() -> None:
    # An unset YDK_COMPONENTS_ROUTE means no route components exist in the
    # project at all (zero-component baseline) -- treated as an empty route
    # list so GeneratedEndpoints.cs is still emitted (empty). A var that IS
    # set but points at a missing file is a genuine misconfiguration and
    # still fails loudly.
    route_path = os.environ.get("YDK_COMPONENTS_ROUTE")
    if route_path is None:
        routes: list[dict] = []
    elif not route_path or not Path(route_path).exists():
        print("Error: YDK_COMPONENTS_ROUTE not set or file not found", file=sys.stderr)
        sys.exit(1)
    else:
        routes = _load_yaml_list(route_path)

    contract_path = os.environ.get("YDK_COMPONENTS_CONTRACT", "")
    contracts = _load_yaml_list(contract_path) if contract_path and Path(contract_path).exists() else []
    index = build_service_index(contracts)

    # Group by PascalCase tag so "orders" and "Orders" share one file.
    groups: dict[str, list[dict]] = {}
    for ep in routes:
        groups.setdefault(tag_class_prefix(route_tag(ep)), []).append(ep)

    templates_dir = Path(__file__).parent.parent / "templates" / "api"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("endpoints.cs.j2")

    output = []
    for tag in sorted(groups):
        context = build_tag_context(tag, groups[tag], index)
        content = template.render(**context).rstrip() + "\n"
        output.append({"path": f"Api/Endpoints/{context['tag']}Endpoints.cs", "content": content})

    aggregate_template = env.get_template("generated_endpoints.cs.j2")
    aggregate_content = aggregate_template.render(tags=sorted(groups)).rstrip() + "\n"
    output.append({"path": "Api/Endpoints/GeneratedEndpoints.cs", "content": aggregate_content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

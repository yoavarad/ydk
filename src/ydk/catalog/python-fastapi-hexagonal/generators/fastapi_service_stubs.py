#!/usr/bin/env python3
"""
Generator: service-stubs
Generate service class stubs with Protocol-based DI (constructor injection).
CRUD methods are fully implemented by delegating to repository ports.
Complex business logic methods get `raise NotImplementedError` with TODO markers.

Input: YDK contract components
Output: app/core/services/{service_snake}.py
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
from _context.naming import derive_name, port_module_name, sanitize_module_name, to_snake
from _context.todos import service_todo
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def _derive_error_class(raw: str) -> str:
    """Convert an YDK error ID to a PascalCase error class name.

    "ydk:error:strategy/strategy-not-found" -> "StrategyNotFoundError"
    "ydk:error:broker/AlpacaAdapterError" -> "AlpacaAdapterError"
    "ydk:error:auth/token-expired-error" -> "TokenExpiredError"
    "StrategyNotFoundError" -> "StrategyNotFoundError" (passthrough)
    """
    if ":" in raw or "/" in raw:
        # YDK ID format: take last segment after /
        if "/" in raw:
            slug = raw.rsplit("/", 1)[1]
        else:
            slug = raw.rsplit(":", 1)[1]

        # If already PascalCase (starts with uppercase, no hyphens): use as-is
        if slug[0].isupper() and "-" not in slug and "_" not in slug:
            name = slug
        else:
            # kebab-case or snake_case: convert to PascalCase
            parts = slug.replace("_", "-").split("-")
            name = "".join(p.capitalize() for p in parts if p)

        # Strip trailing "Error" suffix if present, then always append "Error" once
        if name.endswith("Error"):
            name = name[: -len("Error")]
        name += "Error"
        return name
    return raw


def _indent_description(text: str, indent: str = "    ") -> str:
    """Ensure multi-line descriptions are properly indented."""
    if not text:
        return text
    lines = text.split("\n")
    return ("\n" + indent).join(lines)


def _comment_description(text: str) -> str:
    """Ensure multi-line descriptions are properly prefixed for # comments."""
    if not text:
        return text
    lines = text.split("\n")
    result = [lines[0]]
    for line in lines[1:]:
        stripped = line.strip()
        if stripped:
            result.append("    # " + stripped)
        else:
            result.append("    #")
    return "\n".join(result)


TYPE_MAP = {
    "str": "str",
    "string": "str",
    "text": "str",
    "int": "int",
    "integer": "int",
    "bigint": "int",
    "float": "float",
    "bool": "bool",
    "boolean": "bool",
    "uuid": "UUID",
    "UUID": "UUID",
    "datetime": "datetime",
    "date": "date",
    "bytes": "bytes",
    "json": "dict",
    "jsonb": "dict",
    "None": "None",
    "null": "None",
    "void": "None",
    "Decimal": "Decimal",
    "decimal": "Decimal",
    "callable": "Any",
    "Any": "Any",
    "any": "Any",
    "enum": "str",
    "dict": "dict",
}
PRIMITIVES = {
    "None",
    "str",
    "int",
    "float",
    "bool",
    "dict",
    "list",
    "UUID",
    "datetime",
    "date",
    "bytes",
    "Decimal",
    "Any",
}


def map_type(t: str) -> str:
    t = t.strip()
    if t.lower().startswith("optional[") and t.endswith("]"):
        return f"{map_type(t[9:-1])} | None"
    if t.lower().startswith("list["):
        return f"list[{map_type(t[5:-1])}]"
    # Handle union types with pipe (e.g. "Decimal | null", "Decimal|null", "str | None")
    if "|" in t:
        parts = [map_type(p.strip()) for p in t.split("|")]
        return " | ".join(parts)
    mapped = TYPE_MAP.get(t, t)
    # Entity types (capitalized, not primitive) need Model suffix to match SQLAlchemy class names
    if mapped == t and mapped[0].isupper() and mapped not in PRIMITIVES and not mapped.endswith("Model"):
        return f"{mapped}Model"
    return mapped


# ---------------------------------------------------------------------------
# CRUD detection and implementation generation
# ---------------------------------------------------------------------------

# Method names that indicate CRUD operations implementable from repo delegation
CRUD_METHOD_PATTERNS = {
    "get": "get",
    "get_by_id": "get",
    "find": "get",
    "find_by_id": "get",
    "list": "list",
    "list_all": "list",
    "list_items": "list",
    "create": "create",
    "create_item": "create",
    "update": "update",
    "delete": "delete",
    "hard_delete": "delete",
    "remove": "delete",
    "exists": "exists",
}


def _classify_crud(method_name: str, params: list[dict], return_type: str, service_name: str) -> str | None:
    """Classify a method name as a CRUD operation type or None if complex.

    Returns one of: 'get', 'list', 'create', 'update', 'delete', 'exists', or None.

    Uses heuristics:
    - Method name must match CRUD patterns
    - For get/find: must have an ID param and return the service's own entity type
    - For list: must return a list type
    - For methods like get_portfolio, get_orders: these are complex (different entity type)
    """
    # Derive the entity name from the service name (StrategyService -> Strategy)
    entity_stem = service_name.replace("Service", "")

    # Exact match first
    if method_name in CRUD_METHOD_PATTERNS:
        return CRUD_METHOD_PATTERNS[method_name]

    # Prefix-based matching with additional checks
    lower = method_name.lower()

    if lower.startswith("get_") or lower.startswith("find_"):
        # Only classify as CRUD get if it returns the service's own entity type
        # get_portfolio, get_orders, get_equity_curve etc. are complex methods
        suffix = lower.removeprefix("get_").removeprefix("find_")
        # If suffix contains "by_id" or is just "item"/"entity" pattern, it's CRUD
        if suffix in ("by_id", "one", "by_pk"):
            return "get"
        # If the method name is just "get_{entity}" where entity matches the service
        entity_snake = to_snake(entity_stem).lower()
        if suffix == entity_snake or suffix == f"{entity_snake}s":
            return "get"
        # Otherwise it's a complex retrieval (get_portfolio, get_orders, etc.)
        return None

    if lower.startswith("list_"):
        return "list"
    if lower.startswith("create_"):
        return "create"
    if lower.startswith("update_"):
        return "update"
    if lower.startswith("delete_") or lower.startswith("remove_"):
        return "delete"

    return None


def _find_primary_repo(dependencies: list[dict]) -> dict | None:
    """Find the primary repository port among dependencies.

    Repository ports typically end with 'RepositoryPort' or 'Repository'.
    Returns the first one found.
    """
    for dep in dependencies:
        if "repository" in dep["type"].lower() or "repo" in dep["attr_name"].lower():
            return dep
    return None


def _build_crud_body(
    crud_type: str,
    method: dict,
    primary_repo: dict | None,
    error_classes: list[str],
    service_name: str,
) -> list[str] | None:
    """Build the implementation body lines for a CRUD method.

    Returns a list of code lines (without leading spaces - template handles indentation),
    or None if no implementation can be generated.
    """
    if primary_repo is None:
        return None

    repo_attr = f"self._{primary_repo['attr_name']}"
    params = method.get("params", [])

    # Derive entity name from return type for error messages
    entity_name = service_name.replace("Service", "")

    # Find the appropriate not-found error class
    not_found_error = None
    for ec in error_classes:
        if "not_found" in to_snake(ec).lower() or "notfound" in ec.lower():
            not_found_error = ec
            break
    if not_found_error is None and error_classes:
        # Derive one from entity name
        not_found_error = f"{entity_name}NotFoundError"

    if crud_type == "get":
        # Find the ID param (first param that looks like an ID)
        id_param = None
        for p in params:
            pname = p["name"]
            if pname.endswith("_id") or pname == "id" or pname == "item_id":
                id_param = pname
                break
        if id_param is None and params:
            id_param = params[0]["name"]

        if id_param is None:
            return None

        lines = [
            f"result = {repo_attr}.get({id_param})",
            "if result is None:",
        ]
        if not_found_error:
            lines.append(f'    raise {not_found_error}(f"{entity_name} {{{id_param}}} not found")')
        else:
            lines.append(f'    raise ValueError(f"{entity_name} {{{id_param}}} not found")')
        lines.append("return result")
        return lines

    elif crud_type == "list":
        # Pass filter params to repo if any
        if params:
            filter_args = ", ".join(f"{p['name']}={p['name']}" for p in params)
            return [f"return {repo_attr}.list({filter_args})"]
        return [f"return {repo_attr}.list()"]

    elif crud_type == "create":
        # Find the data param (typically named 'data' or a Create schema)
        data_param = None
        data_is_schema = False
        for p in params:
            pname = p["name"]
            ptype = p["type"]
            if "Create" in ptype or "Update" in ptype:
                data_param = pname
                data_is_schema = True
                break
            if pname == "data":
                data_param = pname
                # Check if it's a Pydantic model (not a plain dict)
                data_is_schema = ptype not in ("dict", "Any")
                break
        if data_param and data_is_schema:
            return [f"return {repo_attr}.create(**{data_param}.model_dump())"]
        elif data_param:
            # Plain dict — pass directly as kwargs
            return [f"return {repo_attr}.create(**{data_param})"]
        else:
            # Pass all params as kwargs
            kwargs = ", ".join(f"{p['name']}={p['name']}" for p in params)
            return [f"return {repo_attr}.create({kwargs})"]

    elif crud_type == "update":
        # Find ID param and data param
        id_param = None
        data_param = None
        data_is_schema = False
        for p in params:
            pname = p["name"]
            ptype = p["type"]
            if pname.endswith("_id") or pname == "id":
                id_param = pname
            elif "Update" in ptype or "Create" in ptype:
                data_param = pname
                data_is_schema = True
            elif pname == "data":
                data_param = pname
                data_is_schema = ptype not in ("dict", "Any")

        if id_param is None and params:
            id_param = params[0]["name"]

        if id_param is None:
            return None

        lines = [f"self.get({id_param})  # raises if not found"]
        if data_param and data_is_schema:
            lines.append(f"updates = {data_param}.model_dump(exclude_unset=True)")
            lines.append(f"return {repo_attr}.update({id_param}, **updates)")
        elif data_param:
            lines.append(f"return {repo_attr}.update({id_param}, **{data_param})")
        else:
            # No data param — pass remaining params as kwargs
            other_params = [p for p in params if p["name"] != id_param]
            if other_params:
                kwargs = ", ".join(f"{p['name']}={p['name']}" for p in other_params)
                lines.append(f"return {repo_attr}.update({id_param}, {kwargs})")
            else:
                lines.append(f"return {repo_attr}.update({id_param})")
        return lines

    elif crud_type == "delete":
        # Find the ID param
        id_param = None
        for p in params:
            pname = p["name"]
            if pname.endswith("_id") or pname == "id":
                id_param = pname
                break
        if id_param is None and params:
            id_param = params[0]["name"]

        if id_param is None:
            return None

        lines = [
            f"self.get({id_param})  # raises if not found",
            f"{repo_attr}.delete({id_param})",
        ]
        return lines

    elif crud_type == "exists":
        id_param = None
        for p in params:
            pname = p["name"]
            if pname.endswith("_id") or pname == "id":
                id_param = pname
                break
        if id_param is None and params:
            id_param = params[0]["name"]
        if id_param:
            return [f"return {repo_attr}.get({id_param}) is not None"]

    return None


def build_service_context(uc: dict) -> dict:
    """Build the Jinja2 template context for one service."""
    name = derive_name(uc)
    service_name = name if name.endswith("Service") else f"{name}Service"
    raw_ports = uc.get("ports", [])
    port_names = [p["name"] if isinstance(p, dict) else p for p in raw_ports]
    methods_raw_src = uc.get("methods", [])
    # Normalize YDK map-format methods to list format
    if isinstance(methods_raw_src, dict):
        methods_raw = []
        for method_name, method_def in methods_raw_src.items():
            m = {"name": method_name, **(method_def if isinstance(method_def, dict) else {})}
            # Map YDK 'params' to legacy 'input'
            if "params" in m and "input" not in m:
                m["input"] = m["params"]
            # Map YDK 'returns' to legacy 'output'
            if "returns" in m and "output" not in m:
                ret = m["returns"]
                m["output"] = ret.get("type", "None") if isinstance(ret, dict) else ret
            # Map YDK 'raises' to legacy 'errors'
            if "raises" in m and "errors" not in m:
                m["errors"] = [{"name": r} if isinstance(r, str) else r for r in m["raises"]]
            methods_raw.append(m)
    else:
        methods_raw = methods_raw_src
    # Collect all unique error classes from all method error lists
    seen_errors: set[str] = set()
    errors = []
    for m in methods_raw:
        for e in m.get("errors", []):
            raw_ename = e["name"] if isinstance(e, dict) else str(e)
            # Derive class name from YDK error ID: "ydk:error:strategy/strategy-not-found" -> "StrategyNotFoundError"
            ename = _derive_error_class(raw_ename)
            if ename not in seen_errors:
                seen_errors.add(ename)
                errors.append({"name": ename})

    imports = set()

    # Dependencies: ports only — never inject Session into service layer
    dependencies = []
    for pname in port_names:
        snake = to_snake(pname)
        module_name = port_module_name(pname)
        imports.add(f"from app.core.ports.{module_name} import {pname}")
        attr = snake.removesuffix("_port") if snake.endswith("_port") else snake
        dependencies.append({"param_name": snake, "attr_name": attr, "type": pname})

    # Port services (name ends in "Port" before adding "Service") wrap a port interface.
    # These services are inherently async since they wrap external adapters.
    # If no explicit ports are declared, inject the port itself as a dependency.
    base_name = name if not name.endswith("Service") else name[: -len("Service")]
    is_port_service = base_name.endswith("Port")
    if is_port_service and not dependencies:
        port_name = base_name  # e.g. "MarketDataPort"
        snake = to_snake(port_name)
        module_name = port_module_name(port_name)
        imports.add(f"from app.core.ports.{module_name} import {port_name}")
        attr = snake.removesuffix("_port") if snake.endswith("_port") else snake
        dependencies.append({"param_name": snake, "attr_name": attr, "type": port_name})

    # Error classes
    error_classes = [e["name"] for e in errors]

    # Collect type references from methods for imports
    all_type_refs = set()
    for m in methods_raw:
        # input can be a dict like {status: optional[str]}, {fields: [{name:, type:}]}, or list of dicts
        inp = m.get("input", {})
        if isinstance(inp, dict) and "fields" in inp:
            for arg in inp["fields"]:
                all_type_refs.add(map_type(arg.get("type", "str")))
        elif isinstance(inp, dict):
            for v in inp.values():
                if isinstance(v, dict):
                    all_type_refs.add(map_type(v.get("type", "Any")))
                else:
                    all_type_refs.add(map_type(str(v)))
        elif isinstance(inp, list):
            for arg in inp:
                all_type_refs.add(map_type(arg.get("type", "str")))
        # output can be a string like "list[ProjectModel]" or a dict with "type"
        out = m.get("output", "None")
        if isinstance(out, dict):
            all_type_refs.add(map_type(out.get("type", "None")))
        else:
            all_type_refs.add(map_type(str(out)))

    if not methods_raw:
        inp = uc.get("input", {})
        out = uc.get("output", {})
        output_type = map_type(out.get("type", "None")) if out else "None"
        all_type_refs.add(output_type)
        for f in inp.get("fields", []):
            all_type_refs.add(map_type(f.get("type", "str")))

    for t in all_type_refs:
        if "UUID" in t:
            imports.add("from uuid import UUID")
        if "datetime" in t:
            imports.add("from datetime import datetime")
        if "date" in t and "datetime" not in t:
            imports.add("from datetime import date")
        if "Decimal" in t:
            imports.add("from decimal import Decimal")
        if "Any" in t:
            imports.add("from typing import Any")
        entity_names = re.findall(r"\b([A-Z][A-Za-z0-9]+)\b", t)
        for ename in entity_names:
            if ename not in PRIMITIVES:
                # Normalize: SQLAlchemy model classes use Model suffix
                model_cls = ename if ename.endswith("Model") else f"{ename}Model"
                module = sanitize_module_name(to_snake(model_cls.removesuffix("Model")))
                imports.add(f"from app.core.models.{module} import {model_cls}")

    # Find primary repository port for CRUD delegation
    primary_repo = _find_primary_repo(dependencies)

    # Build methods
    methods = []
    if methods_raw:
        for m in methods_raw:
            is_async = m.get("async", False) or is_port_service
            # output: string like "list[ProjectModel]" or dict with "type"
            raw_out = m.get("output", "None")
            if isinstance(raw_out, dict):
                returns = map_type(raw_out.get("type", "None"))
            else:
                returns = map_type(str(raw_out))
            # input: dict like {status: optional[str]}, {fields: [{name:, type:}]}, or list of dicts
            params = []
            raw_inp = m.get("input") or m.get("args") or {}
            if isinstance(raw_inp, dict) and "fields" in raw_inp:
                for a in raw_inp["fields"]:
                    pt = map_type(a.get("type", "str"))
                    default = "None" if "| None" in pt or "Optional" in pt else None
                    params.append({"name": a["name"], "type": pt, "default": default})
            elif isinstance(raw_inp, dict):
                for param_name, param_value in raw_inp.items():
                    if isinstance(param_value, dict):
                        pt = map_type(param_value.get("type", "Any"))
                    else:
                        pt = map_type(str(param_value))
                    default = "None" if "| None" in pt or "Optional" in pt else None
                    params.append({"name": param_name, "type": pt, "default": default})
            elif isinstance(raw_inp, list):
                for a in raw_inp:
                    pt = map_type(a.get("type", "str"))
                    default = "None" if "| None" in pt or "Optional" in pt else None
                    params.append({"name": a["name"], "type": pt, "default": default})
            # Sort: required params (no default) before optional params (with default)
            params.sort(key=lambda p: p["default"] is not None)
            # Preprocess description to avoid broken # comment lines on continuation
            m_for_todo = dict(m)
            if "description" in m_for_todo:
                m_for_todo["description"] = _comment_description(m_for_todo["description"])
            todo_lines = service_todo(service_name, m_for_todo.get("name", "?"), m_for_todo)
            method_name = m["name"]
            # When a method is named ``list`` and returns ``list[...]``, ty
            # resolves ``list`` as the method itself instead of the builtin.
            # Work around this by using a ``_List`` alias defined at module level.
            needs_list_alias = method_name == "list" and returns.startswith("list[")
            display_return = returns.replace("list[", "_List[", 1) if needs_list_alias else returns

            # Determine if this is a CRUD method and generate implementation body
            crud_type = _classify_crud(method_name, params, display_return, service_name)
            crud_body = None
            if crud_type and primary_repo:
                crud_body = _build_crud_body(
                    crud_type=crud_type,
                    method={"params": params, "return_type": display_return},
                    primary_repo=primary_repo,
                    error_classes=error_classes,
                    service_name=service_name,
                )

            methods.append(
                {
                    "name": method_name,
                    "description": _comment_description(m.get("description", "")),
                    "is_async": is_async,
                    "return_type": display_return,
                    "needs_list_alias": needs_list_alias,
                    "params": params,
                    "todo_lines": todo_lines,
                    "crud_body": crud_body,
                }
            )
    else:
        inp = uc.get("input", {})
        out = uc.get("output", {})
        output_type = map_type(out.get("type", "None")) if out else "None"
        input_fields = inp.get("fields", [])
        params = [{"name": f["name"], "type": map_type(f.get("type", "str")), "default": None} for f in input_fields]
        methods.append(
            {
                "name": "execute",
                "is_async": True,
                "return_type": output_type,
                "params": params,
                "todo_lines": service_todo(service_name, "execute", {}),
                "crud_body": None,
            }
        )

    raw_description = uc.get("description", f"{service_name} service")
    needs_list_alias = any(m.get("needs_list_alias") for m in methods)
    return {
        "service_name": service_name,
        "description": _indent_description(raw_description),
        "imports": sorted(imports),
        "error_classes": error_classes,
        "dependencies": dependencies,
        "methods": methods,
        "needs_list_alias": needs_list_alias,
    }


def _singularize(word: str) -> str:
    """Singularize a snake_case word."""
    try:
        import inflect

        _p = inflect.engine()
        singular = _p.singular_noun(word)
        return singular if singular else word
    except ImportError:
        if word.endswith("ies") and len(word) > 3:
            return word[:-3] + "y"
        if word.endswith("es") and not word.endswith("ses"):
            return word[:-2]
        if word.endswith("s") and not word.endswith("ss"):
            return word[:-1]
        return word


def _to_camel(name: str) -> str:
    return "".join(w.capitalize() for w in re.split(r"[_\-/]", name) if w)


def _infer_domain_services(
    route_data: list[dict],
    entity_data: list[dict],
    contract_names: set[str],
) -> list[dict]:
    """Infer domain services from route tags + entities.

    For each unique route tag (e.g. 'strategies'), creates a service context
    with the matching entity's repository port as a dependency and CRUD methods
    derived from the HTTP methods present.

    Skips tags that already have a matching contract-generated service.
    """
    from _context.naming import derive_name as dn

    # Group routes by tag
    groups: dict[str, list] = {}
    for ep in route_data:
        segments = [p for p in ep.get("path", "").split("/") if p and not p.startswith("{")]
        if segments and segments[0] == "api":
            segments = segments[1:]
        raw_tag = segments[0] if segments else "root"
        tag = re.sub(r"[^a-z0-9]+", "_", raw_tag.lower()).strip("_") or "root"
        groups.setdefault(tag, []).append(ep)

    # Build entity index: entity_snake -> entity dict
    entity_index: dict[str, dict] = {}
    for entity in entity_data:
        ename = dn(entity)
        entity_index[to_snake(ename)] = entity

    inferred: list[dict] = []
    for tag, endpoints in groups.items():
        # Infer service name from tag: 'strategies' -> 'StrategyService'
        singular = _singularize(tag.replace("_", " ").replace("-", " ").replace(" ", "_"))
        svc_name = _to_camel(singular) + "Service"

        # Skip if contract already generates this service
        if svc_name in contract_names:
            continue

        # Find matching entity
        entity = entity_index.get(singular)
        if not entity:
            # Try without singularization
            entity = entity_index.get(tag)
        if not entity:
            # Try other variations
            for ekey in entity_index:
                if ekey == singular or ekey.startswith(singular) or singular.startswith(ekey):
                    entity = entity_index[ekey]
                    break

        # Build synthetic contract for this domain service
        entity_name = dn(entity) if entity else None
        port_name = f"{entity_name}RepositoryPort" if entity_name else None

        # Determine CRUD methods from endpoints
        return_entity = entity_name or "dict"
        methods: dict[str, dict] = {}
        for ep in endpoints:
            http_method = ep.get("method", "GET").upper()
            path = ep.get("path", "")
            segments = [s for s in path.strip("/").split("/") if s]
            has_id = any(s.startswith("{") for s in segments)

            if http_method == "GET" and not has_id:
                methods.setdefault(
                    "list",
                    {
                        "description": f"List all {tag}",
                        "params": {},
                        "returns": {"type": f"list[{return_entity}]"},
                    },
                )
                # Add query params
                query = (ep.get("request", {}) or {}).get("query", {})
                if query:
                    methods["list"]["params"] = {
                        k: v.get("type", "str") if isinstance(v, dict) else str(v) for k, v in query.items()
                    }
            elif http_method == "GET" and has_id:
                # Find the path param
                id_params = [s.strip("{}") for s in segments if s.startswith("{")]
                id_param = id_params[0] if id_params else "id"
                # Check for sub-resource after id
                after_id = []
                found_id = False
                for s in segments:
                    if found_id and not s.startswith("{"):
                        after_id.append(s)
                    if s.startswith("{"):
                        found_id = True
                if not after_id:
                    methods.setdefault(
                        "get",
                        {
                            "description": f"Get a {singular} by ID",
                            "params": {id_param: "int"},
                            "returns": {"type": return_entity},
                            "raises": [f"ydk:error:{singular}/{singular}-not-found"],
                        },
                    )
                else:
                    sub = "_".join(after_id).replace("-", "_")
                    methods.setdefault(
                        f"list_{sub}",
                        {
                            "description": f"List {sub} for a {singular}",
                            "params": {id_param: "int"},
                            "returns": {"type": "list[dict]"},
                        },
                    )
            elif http_method == "POST" and not has_id:
                methods.setdefault(
                    "create",
                    {
                        "description": f"Create a new {singular}",
                        "params": {"data": "dict"},
                        "returns": {"type": return_entity},
                    },
                )
            elif http_method in ("PUT", "PATCH"):
                id_params = [s.strip("{}") for s in segments if s.startswith("{")]
                id_param = id_params[0] if id_params else "id"
                methods.setdefault(
                    "update",
                    {
                        "description": f"Update a {singular}",
                        "params": {id_param: "int", "data": "dict"},
                        "returns": {"type": return_entity},
                        "raises": [f"ydk:error:{singular}/{singular}-not-found"],
                    },
                )
            elif http_method == "DELETE":
                id_params = [s.strip("{}") for s in segments if s.startswith("{")]
                id_param = id_params[0] if id_params else "id"
                methods.setdefault(
                    "delete",
                    {
                        "description": f"Delete a {singular}",
                        "params": {id_param: "int"},
                        "returns": {"type": "None"},
                        "raises": [f"ydk:error:{singular}/{singular}-not-found"],
                    },
                )
            elif http_method == "POST" and has_id:
                # Sub-resource action (e.g. /strategies/{id}/clone)
                after_id = []
                found_id = False
                for s in segments:
                    if found_id and not s.startswith("{"):
                        after_id.append(s)
                    if s.startswith("{"):
                        found_id = True
                if after_id:
                    action = "_".join(after_id).replace("-", "_")
                    id_params = [s.strip("{}") for s in segments if s.startswith("{")]
                    id_param = id_params[0] if id_params else "id"
                    methods.setdefault(
                        action,
                        {
                            "description": f"{action.replace('_', ' ').title()} a {singular}",
                            "params": {id_param: "int"},
                            "returns": {"type": return_entity},
                        },
                    )

        # Build a synthetic contract that build_service_context can process
        synthetic = {
            "id": f"ydk:contract:{tag}/{svc_name}",
            "description": f"Domain service for {tag} management",
            "ports": [{"name": port_name, "type": "repository"}] if port_name else [],
            "methods": methods,
        }
        inferred.append(synthetic)

    return inferred


def main() -> None:
    uc_path = os.environ.get("YDK_COMPONENTS_CONTRACT", "")
    route_path = os.environ.get("YDK_COMPONENTS_ROUTE", "")
    entity_path = os.environ.get("YDK_COMPONENTS_ENTITY", "")

    # Set up Jinja2
    templates_dir = Path(__file__).parent.parent / "templates" / "services"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("service_stub.py.j2")

    output = []
    contract_names: set[str] = set()

    # Phase 1: Generate services from contract components (port wrappers)
    if uc_path and Path(uc_path).exists():
        data = yaml.safe_load(Path(uc_path).read_text(encoding="utf-8")) or {}
        for uc in data if isinstance(data, list) else []:
            context = build_service_context(uc)
            contract_names.add(context["service_name"])
            content = template.render(**context).rstrip() + "\n"
            snake = to_snake(context["service_name"])
            svc_class = context["service_name"]
            output.append({"path": f"app/core/services/{snake}/service.py", "content": content})
            error_names = context.get("error_classes", [])
            all_exports = sorted([svc_class] + error_names)
            exports_str = ", ".join(all_exports)
            all_list = ", ".join(f'"{n}"' for n in all_exports)
            init_content = (
                f"from __future__ import annotations\n\nfrom .service import {exports_str}\n\n__all__ = [{all_list}]\n"
            )
            output.append({"path": f"app/core/services/{snake}/__init__.py", "content": init_content})

    # Phase 2: Generate domain services from routes + entities
    route_data = []
    entity_data = []
    if route_path and Path(route_path).exists():
        route_data = yaml.safe_load(Path(route_path).read_text(encoding="utf-8")) or []
        if not isinstance(route_data, list):
            route_data = []
    if entity_path and Path(entity_path).exists():
        entity_data = yaml.safe_load(Path(entity_path).read_text(encoding="utf-8")) or []
        if not isinstance(entity_data, list):
            entity_data = []

    if route_data and entity_data:
        inferred = _infer_domain_services(route_data, entity_data, contract_names)
        for uc in inferred:
            context = build_service_context(uc)
            content = template.render(**context).rstrip() + "\n"
            snake = to_snake(context["service_name"])
            svc_class = context["service_name"]
            output.append({"path": f"app/core/services/{snake}/service.py", "content": content})
            error_names = context.get("error_classes", [])
            all_exports = sorted([svc_class] + error_names)
            exports_str = ", ".join(all_exports)
            all_list = ", ".join(f'"{n}"' for n in all_exports)
            init_content = (
                f"from __future__ import annotations\n\nfrom .service import {exports_str}\n\n__all__ = [{all_list}]\n"
            )
            output.append({"path": f"app/core/services/{snake}/__init__.py", "content": init_content})

    if not output:
        print("[]")
        return

    print(json.dumps(output))


if __name__ == "__main__":
    main()

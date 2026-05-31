#!/usr/bin/env python3
"""
Generator: query-hooks
Generates TanStack Query hooks from openapi-spec (or route components fallback).
Also emits src/shared/lib/query-keys.ts with centralised query key factory.

Input: ODK_ARTIFACT_OPENAPI (preferred) | ODK_COMPONENTS_ROUTE (fallback)
Output: {domain}.ts per API domain + query-keys.ts
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _context.naming import to_camel, to_pascal
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def derive_hook_name(ep: dict) -> str:
    """
    Derive a React hook name from an API endpoint definition.

    Priority:
      1. maps_to_use_case ServiceName.method_name -> map method prefix to hook prefix
      2. HTTP method + path heuristics

    Mapping:
      GET  /resources          -> useResources  (plural list)
      GET  /resources/{id}     -> useResource   (singular, strip trailing 's' if present)
      POST /resources          -> useCreateResource
      PUT  /resources/{id}     -> useUpdateResource
      PATCH /resources/{id}    -> useUpdateResource
      DELETE /resources/{id}   -> useDeleteResource
    """
    uc = ep.get("maps_to_use_case", "") or ep.get("maps_to", "")
    method = ep.get("method", "GET").upper()
    path = ep.get("path", "")

    if uc and "." in uc:
        method_name = uc.split(".")[-1]
        method_prefix_map = {
            "get": "use",
            "list": "use",
            "create": "useCreate",
            "update": "useUpdate",
            "delete": "useDelete",
        }
        for prefix, hook_prefix in method_prefix_map.items():
            if method_name.startswith(prefix):
                remainder = method_name[len(prefix) :]
                return f"{hook_prefix}{to_pascal(remainder)}"

    return _path_to_hook_name(method, path)


def _path_to_hook_name(method: str, path: str) -> str:
    """Derive a hook name from HTTP method + path."""
    clean = re.sub(r"\[[^\]]+\]|\{[^}]+\}", "", path)
    segments = [s for s in clean.split("/") if s and s != "api"]
    if not segments:
        return f"use{to_pascal(method.lower())}"

    method_upper = method.upper()
    resource = segments[-1] if segments else "resource"
    resource_pascal = to_pascal(resource)

    method_prefix_map = {
        "POST": "useCreate",
        "PUT": "useUpdate",
        "PATCH": "useUpdate",
        "DELETE": "useDelete",
    }

    if method_upper in method_prefix_map:
        return f"{method_prefix_map[method_upper]}{resource_pascal}"

    # GET — check if path has dynamic segment to distinguish list vs single
    if re.search(r"\[[^\]]+\]|\{[^}]+\}", path):
        # Singular: strip trailing 's' if last resource is plural
        singular = resource_pascal.rstrip("s") if resource_pascal.endswith("s") else resource_pascal
        return f"use{singular}"
    return f"use{resource_pascal}"


def has_path_params(path: str) -> bool:
    return bool(re.search(r"\[[^\]]+\]|\{[^}]+\}", path))


def extract_path_params(path: str) -> list[str]:
    matches = re.findall(r"\[([^\]]+)\]|\{([^}]+)\}", path)
    return [m[0] or m[1] for m in matches]


def build_sdk_service_name(domain: str) -> str:
    return f"{to_camel(domain)}Service"


def build_sdk_method_name(ep: dict) -> str:
    """Build the SDK method name (what openapi-ts generates)."""
    method = ep.get("method", "GET").upper()
    path = ep.get("path", "")
    clean = re.sub(r"\[[^\]]+\]|\{[^}]+\}", "ById", path)
    parts = [s for s in clean.replace("-", "_").split("/") if s and s != "api"]
    combined = "_".join(parts)
    return to_camel(f"{method.lower()}_{combined}")


def build_sdk_call(ep: dict, service_name: str) -> str:
    """Build the SDK function call expression for this endpoint."""
    sdk_method = build_sdk_method_name(ep)
    path = ep.get("path", "")
    param_names = extract_path_params(path)
    if param_names:
        args = ", ".join(f"{n}: {n}" for n in param_names)
        return f"{service_name}.{sdk_method}({{ {args} }})"
    return f"{service_name}.{sdk_method}()"


def build_domain_context(domain: str, endpoints: list[dict]) -> dict:
    """Build Jinja2 template context for one domain's hooks file."""
    service_name = build_sdk_service_name(domain)

    tanstack_imports = set()
    hooks = []

    for ep in endpoints:
        method = ep.get("method", "GET").upper()
        path = ep.get("path", "")
        hook_name = derive_hook_name(ep)
        is_mutation = method != "GET"

        if is_mutation:
            tanstack_imports.update(["useMutation", "useQueryClient"])
            hooks.append(
                {
                    "name": hook_name,
                    "params": "",
                    "is_mutation": True,
                    "has_path_params": False,
                    "sdk_call": f"{service_name}.{build_sdk_method_name(ep)}",
                    "domain": to_camel(domain),
                    "key_arg": "",
                    "enabled_expr": "",
                    "list_params": "",
                }
            )
        else:
            tanstack_imports.add("useQuery")
            path_params = extract_path_params(path)
            has_pp = bool(path_params)

            if has_pp:
                param_sig = ", ".join(f"{n}: number" for n in path_params)
                key_arg = path_params[0] if len(path_params) == 1 else f"[{', '.join(path_params)}]"
                enabled_expr = " && ".join(f"!!{n}" for n in path_params)
                sdk_call_str = build_sdk_call(ep, service_name)
                hooks.append(
                    {
                        "name": hook_name,
                        "params": param_sig,
                        "is_mutation": False,
                        "has_path_params": True,
                        "sdk_call": sdk_call_str,
                        "domain": to_camel(domain),
                        "key_arg": key_arg,
                        "enabled_expr": enabled_expr,
                        "list_params": "",
                    }
                )
            else:
                raw_params = ep.get("request", {}) or {}
                query_params = raw_params.get("query_params", []) if isinstance(raw_params, dict) else []
                list_params = "params" if query_params else ""
                param_sig = ""
                if query_params:
                    param_type_parts = []
                    for qp in query_params:
                        qp_name = qp.get("name", qp) if isinstance(qp, dict) else qp
                        param_type_parts.append(f"{qp_name}?: string")
                    param_sig = f"params?: {{ {'; '.join(param_type_parts)} }}"

                hooks.append(
                    {
                        "name": hook_name,
                        "params": param_sig,
                        "is_mutation": False,
                        "has_path_params": False,
                        "sdk_call": f"{service_name}.{build_sdk_method_name(ep)}({list_params})",
                        "domain": to_camel(domain),
                        "key_arg": "",
                        "enabled_expr": "",
                        "list_params": list_params,
                    }
                )

    return {
        "domain": domain,
        "service_name": service_name,
        "tanstack_imports": sorted(tanstack_imports),
        "type_imports": [],
        "hooks": hooks,
    }


def _endpoints_from_openapi(spec: dict) -> list[dict]:
    """Convert OpenAPI paths to endpoint dicts compatible with build_domain_context."""
    endpoints = []
    for path, path_item in spec.get("paths", {}).items():
        for method, op in path_item.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            params = op.get("parameters", []) if isinstance(op, dict) else []
            query_params = [{"name": p["name"]} for p in params if isinstance(p, dict) and p.get("in") == "query"]
            endpoints.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "request": {"query_params": query_params},
                }
            )
    return endpoints


def _endpoints_from_routes(routes: list[dict]) -> list[dict]:
    """Convert ODK route components to endpoint dicts."""
    endpoints = []
    for route in routes:
        method = route.get("method", "GET").upper()
        path = route.get("path", "")
        if not path:
            continue
        endpoints.append(
            {
                "method": method,
                "path": path,
                "maps_to_use_case": route.get("maps_to_use_case", ""),
                "maps_to": route.get("maps_to", ""),
                "request": route.get("request", {}),
            }
        )
    return endpoints


def main() -> None:
    openapi_path = os.environ.get("ODK_ARTIFACT_OPENAPI", "")
    if openapi_path and Path(openapi_path).exists():
        spec = json.loads(Path(openapi_path).read_text(encoding="utf-8"))
        endpoints = _endpoints_from_openapi(spec)
    else:
        routes_path = os.environ.get("ODK_COMPONENTS_ROUTE", "")
        if not routes_path or not Path(routes_path).exists():
            print(
                "Warning: Neither ODK_ARTIFACT_OPENAPI nor ODK_COMPONENTS_ROUTE available — query-hooks deferred.",
                file=sys.stderr,
            )
            print(json.dumps([]))
            return
        routes = yaml.safe_load(Path(routes_path).read_text(encoding="utf-8")) or []
        if isinstance(routes, dict):
            routes = routes.get("routes", routes.get("api_contracts", []))
        endpoints = _endpoints_from_routes(routes)

    # Group by domain (first path segment)
    groups: dict[str, list] = {}
    for ep in endpoints:
        path = ep.get("path", "")
        segments = [
            s
            for s in path.strip("/").split("/")
            if s and s != "api" and not s.startswith("{") and not s.startswith("[")
        ]
        domain = re.sub(r"[^a-z0-9]+", "-", segments[0].lower()).strip("-") if segments else "root"
        groups.setdefault(domain, []).append(ep)

    # Set up Jinja2 for hook template
    templates_dir = Path(__file__).parent.parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    output = []

    # Emit query-keys.ts
    domains_ctx = [{"name": to_camel(domain), "extra_keys": []} for domain in sorted(groups.keys())]
    qk_template = env.get_template("shared/query-keys.ts.j2")
    qk_content = qk_template.render(domains=domains_ctx).rstrip() + "\n"
    output.append({"path": "query-keys.ts", "content": qk_content})

    # Emit per-domain hooks
    hook_template = env.get_template("features/query-hook.ts.j2")
    for domain, eps in sorted(groups.items()):
        ctx = build_domain_context(domain, eps)
        content = hook_template.render(**ctx).rstrip() + "\n"
        output.append({"path": f"{domain}.ts", "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

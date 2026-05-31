#!/usr/bin/env python3
"""Generate typed Next.js API client from ODK route components"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _context.naming import derive_name


def to_camel(name: str) -> str:
    parts = name.replace("-", "_").split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def path_to_func_name(method: str, path: str) -> str:
    clean = re.sub(r"\{[^}]+\}", "", path)
    parts = [p for p in clean.split("/") if p and p != "api"]
    name = to_camel(f"{method.lower()}_{'_'.join(parts)}" if parts else f"{method.lower()}_root")
    return name


def map_ts_type(t: str) -> str:
    ts_map = {
        "str": "string",
        "int": "number",
        "float": "number",
        "bool": "boolean",
        "uuid": "string",
        "datetime": "Date",
        "date": "Date",
        "json": "Record<string, unknown>",
    }
    t = t.strip()
    if t.startswith("optional["):
        return f"{map_ts_type(t[9:-1])} | null"
    if t.startswith("list["):
        return f"{map_ts_type(t[5:-1])}[]"
    if " | None" in t:
        return f"{map_ts_type(t.replace(' | None', '').strip())} | null"
    return ts_map.get(t, t)


def _resolve_response_type(ep: dict, entity_names: set) -> tuple[str, set[str]]:
    """Resolve the TypeScript return type for an endpoint.

    Returns (ts_type, set_of_entity_names_used).
    """
    used = set()

    # 1. Check responses[].body.type
    responses = ep.get("responses", [])
    success_resp = next((r for r in responses if r.get("status", 0) < 300), None)
    if success_resp:
        body = success_resp.get("body", {})
        if body.get("type"):
            return map_ts_type(body["type"]), used
        if body.get("schema"):
            schema = body["schema"]
            if schema.endswith("[]"):
                base = schema[:-2]
                used.add(base)
                return f"{base}[]", used
            else:
                if schema in entity_names:
                    used.add(schema)
                return schema, used

    # 2. Check response_type at endpoint level
    rt = ep.get("response_type", "")
    if rt:
        if rt.startswith("list[") and rt.endswith("]"):
            inner = rt[5:-1]
            if inner in entity_names:
                used.add(inner)
                return f"{inner}[]", used
            return f"{map_ts_type(inner)}[]", used
        elif rt in entity_names:
            used.add(rt)
            return rt, used
        else:
            return map_ts_type(rt), used

    return "void", used


def generate_client(contracts: list, entity_names: set) -> str:
    lines = [
        "import { apiRequest } from './client';",
        "",
    ]

    all_used_entities: set[str] = set()

    for ep in contracts:
        method = ep["method"].upper()
        path = ep["path"]
        use_case = ep.get("maps_to_use_case", "")
        func_name = path_to_func_name(method, path)

        # Response type
        ret_type, used_entities = _resolve_response_type(ep, entity_names)
        all_used_entities.update(used_entities)

        # Request body
        req_fields = ep.get("request", {}).get("body", {}).get("fields", [])

        # Path params
        path_params = re.findall(r"\{(\w+)\}", path)

        # Build function params
        param_parts = []
        for p in path_params:
            param_parts.append(f"{p}: string")
        if req_fields and method in ("POST", "PUT", "PATCH"):
            fields_str = "; ".join(f"{f['name']}: {map_ts_type(f.get('type', 'str'))}" for f in req_fields)
            param_parts.append(f"body: {{ {fields_str} }}")

        params_str = ", ".join(param_parts)

        # Resolved path expression
        resolved_path = re.sub(r"\{(\w+)\}", r"${\1}", path)
        path_expr = f"`{resolved_path}`" if path_params else f'"{path}"'

        if use_case:
            lines.append(f"// Maps to: {use_case}")
        if req_fields and method in ("POST", "PUT", "PATCH"):
            lines.append(f"export const {func_name} = ({params_str}): Promise<{ret_type}> =>")
            lines.append(
                f"  apiRequest<{ret_type}>({path_expr}, {{ method: '{method}', body: JSON.stringify(body) }});"
            )
        else:
            lines.append(f"export const {func_name} = ({params_str}): Promise<{ret_type}> =>")
            lines.append(f"  apiRequest<{ret_type}>({path_expr});")
        lines.append("")

    # Add entity type imports at the top
    if all_used_entities:
        import_lines = []
        for etype in sorted(all_used_entities):
            # Use lowercase-first convention for entity module names
            module = etype[0].lower() + etype[1:]
            import_lines.append(f"import type {{ {etype} }} from '@/entities/{module}';")
        # Insert after the apiRequest import line (index 3, after the empty line)
        for i, line in enumerate(import_lines):
            lines.insert(3 + i, line)

    return "\n".join(lines)


def main():
    path = os.environ.get("ODK_COMPONENTS_ROUTE", "")
    if not path or not Path(path).exists():
        print("[]")
        return

    # Load data model to know entity names for type resolution
    dm_path = os.environ.get("ODK_COMPONENTS_ENTITY", "")
    entity_names: set[str] = set()
    if dm_path and Path(dm_path).exists():
        dm_data = yaml.safe_load(Path(dm_path).read_text(encoding="utf-8")) or {}
        for entity in dm_data if isinstance(dm_data, list) else []:
            entity_names.add(derive_name(entity))

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    contracts = data if isinstance(data, list) else []
    content = generate_client(contracts, entity_names)
    print(json.dumps([{"path": "endpoints.ts", "content": content}]))


if __name__ == "__main__":
    main()

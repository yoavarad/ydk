#!/usr/bin/env python3
"""
Generator: protocol-ports
Generate Python Protocol port interfaces (structural subtyping) from ports.yaml.
Input: ports.yaml
Output: app/core/ports/{port_snake}.py
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
from _context.naming import port_module_name, to_snake
from jinja2 import Environment, FileSystemLoader, StrictUndefined

TYPE_MAP = {
    "str": "str",
    "string": "str",
    "int": "int",
    "integer": "int",
    "float": "float",
    "bool": "bool",
    "boolean": "bool",
    "uuid": "UUID",
    "UUID": "UUID",
    "datetime": "datetime",
    "date": "date",
    "bytes": "bytes",
    "json": "dict[str, Any]",
    "None": "None",
    "null": "None",
    "void": "None",
    "Decimal": "Decimal",
    "decimal": "Decimal",
    "dict": "dict",
    "Any": "Any",
    "any": "Any",
}

PRIMITIVES = {
    "str",
    "string",
    "int",
    "integer",
    "float",
    "bool",
    "boolean",
    "uuid",
    "UUID",
    "datetime",
    "date",
    "bytes",
    "json",
    "None",
    "null",
    "void",
    "Any",
    "any",
    "Decimal",
    "decimal",
    "dict",
    "list",
}
TYPING_GENERICS = {
    "AsyncGenerator",
    "Generator",
    "AsyncIterator",
    "Iterator",
    "Awaitable",
    "Coroutine",
}


def map_type(t: str) -> str:
    t = t.strip()
    if t.startswith("optional["):
        return f"{map_type(t[9:-1])} | None"
    if t.startswith("list["):
        return f"list[{map_type(t[5:-1])}]"
    # Handle union types with pipe (e.g. "Decimal | null", "str | None")
    if "|" in t and "[" not in t:
        parts = [map_type(p.strip()) for p in t.split("|")]
        return " | ".join(parts)

    # Handle generic types like AsyncGenerator[dict, None]
    bracket_pos = t.find("[")
    if bracket_pos > 0:
        base = t[:bracket_pos]
        inner = t[bracket_pos + 1 : -1]
        inner_parts = []
        depth = 0
        current = ""
        for ch in inner:
            if ch == "[":
                depth += 1
                current += ch
            elif ch == "]":
                depth -= 1
                current += ch
            elif ch == "," and depth == 0:
                inner_parts.append(current.strip())
                current = ""
            else:
                current += ch
        if current.strip():
            inner_parts.append(current.strip())
        mapped_inner = ", ".join(map_type(p) for p in inner_parts)
        mapped_base = TYPE_MAP.get(base, base)
        return f"{mapped_base}[{mapped_inner}]"

    mapped = TYPE_MAP.get(t, t)
    # Entity types (capitalized, not a known primitive/generic) need Model suffix
    if mapped == t and t and t[0].isupper() and t not in PRIMITIVES and t not in TYPING_GENERICS:
        if not mapped.endswith("Model"):
            return f"{mapped}Model"
    return mapped


def _extract_base_types(t: str) -> set[str]:
    """Extract all base type names from a type expression."""
    cleaned = re.sub(r"[\[\],|]", " ", t)
    types = set()
    for part in cleaned.split():
        part = part.strip()
        if part and part not in ("None", ""):
            types.add(part)
    return types


def build_port_context(port: dict) -> dict:
    """Build the Jinja2 template context for one protocol port."""
    name = port["name"]
    methods_raw = port.get("methods", [])

    typing_imports = {"Protocol", "runtime_checkable"}
    extra_typing_imports: set[str] = set()
    imports = {"from __future__ import annotations"}

    # Collect type imports
    all_raw_types: set[str] = set()
    for m in methods_raw:
        for a in m.get("args", []):
            all_raw_types.add(a.get("type", ""))
        all_raw_types.add(m.get("returns", "None"))

    for raw_type in all_raw_types:
        base_types = _extract_base_types(raw_type)
        for t in base_types:
            if t in TYPING_GENERICS:
                extra_typing_imports.add(t)
            elif t == "Any":
                typing_imports.add("Any")
            elif t and t not in PRIMITIVES and t[0].isupper() and t != name:
                snake = to_snake(t)
                # Model classes use the ``Model`` suffix in this template
                model_cls = t if t.endswith("Model") else f"{t}Model"
                imports.add(f"from app.core.models.{snake} import {model_cls}")
            if t == "UUID" or t == "uuid":
                imports.add("from uuid import UUID")
            if t in ("datetime", "date"):
                imports.add(f"from datetime import {t}")
            if t in ("Decimal", "decimal"):
                imports.add("from decimal import Decimal")

    all_typing = sorted(typing_imports | extra_typing_imports)
    imports.add(f"from typing import {', '.join(all_typing)}")

    # Build methods
    methods = []
    needs_list_alias = False
    for m in methods_raw:
        mname = m["name"]
        args = m.get("args", [])
        returns = map_type(m.get("returns", "None"))
        is_async = m.get("async", True)
        arg_str = ", ".join(f"{a['name']}: {map_type(a['type'])}" for a in args)
        if arg_str:
            arg_str = ", " + arg_str
        prefix = "async def" if is_async else "def"
        # When a method is named ``list`` and returns ``list[...]``, ty
        # resolves ``list`` as the method itself.  Use ``_List`` alias.
        if mname == "list" and returns.startswith("list["):
            returns = returns.replace("list[", "_List[", 1)
            needs_list_alias = True
        methods.append(
            {
                "name": mname,
                "prefix": prefix,
                "arg_str": arg_str,
                "returns": returns,
            }
        )

    # Build import_block with proper isort grouping:
    # __future__ → stdlib → third-party → first-party
    future_imps = sorted(i for i in imports if i.startswith("from __future__"))
    stdlib_imps = sorted(i for i in imports if not i.startswith("from __future__") and not i.startswith("from app."))
    firstparty_imps = sorted(i for i in imports if i.startswith("from app."))
    groups = [g for g in [future_imps, stdlib_imps, firstparty_imps] if g]
    import_block = "\n\n".join("\n".join(g) for g in groups)

    return {
        "name": name,
        "import_block": import_block,
        "methods": methods,
        "needs_list_alias": needs_list_alias,
    }


def _normalize_standalone_port(contract: dict) -> dict | None:
    """Convert a standalone port contract to the format expected by build_port_context.

    Standalone port contracts have their name ending in "Port" and methods at top level
    in dict format: {method_name: {params: {...}, returns: {...}}}.
    Returns None if not a standalone port contract.
    """
    from _context.naming import derive_name

    name = derive_name(contract)
    if not name.endswith("Port"):
        return None
    # Must have methods at top level and NOT have a 'ports' field
    if contract.get("ports"):
        return None
    methods_raw = contract.get("methods", {})
    if not methods_raw or not isinstance(methods_raw, dict):
        return None

    # Convert dict-format methods to list-format expected by build_port_context
    methods = []
    for mname, mdef in methods_raw.items():
        if not isinstance(mdef, dict):
            mdef = {}
        # Convert params dict to args list
        params = mdef.get("params", {})
        args = []
        if isinstance(params, dict):
            for pname, pdef in params.items():
                if isinstance(pdef, dict):
                    ptype = pdef.get("type", "str")
                else:
                    ptype = str(pdef) if pdef else "str"
                args.append({"name": pname, "type": ptype})
        elif isinstance(params, list):
            args = params
        # Extract return type
        returns = mdef.get("returns", {})
        if isinstance(returns, dict):
            ret_type = returns.get("type", "None")
        else:
            ret_type = str(returns) if returns else "None"
        methods.append(
            {
                "name": mname,
                "args": args,
                "returns": ret_type,
                "async": mdef.get("async", True),
            }
        )

    return {"name": name, "methods": methods}


def main() -> None:
    path = os.environ.get("ODK_COMPONENTS_CONTRACT", "")
    if not path or not Path(path).exists():
        print("[]")
        return

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    # ODK format: contracts is a list, ports are nested in each contract
    contracts = data if isinstance(data, list) else []
    ports = [port for contract in contracts for port in contract.get("ports", [])]

    # Also handle standalone port contracts (contract IS the port, name ends in "Port")
    for contract in contracts:
        standalone = _normalize_standalone_port(contract)
        if standalone:
            ports.append(standalone)

    # Set up Jinja2
    templates_dir = Path(__file__).parent.parent / "templates" / "ports"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("protocol_port.py.j2")

    output = []
    for port in ports:
        context = build_port_context(port)
        content = template.render(**context).rstrip() + "\n"
        module = port_module_name(port["name"])
        output.append({"path": f"app/core/ports/{module}.py", "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

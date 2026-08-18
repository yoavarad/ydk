#!/usr/bin/env python3
"""
Generator: adapter-stubs
Generate adapter class stubs implementing their declared ports.

Reads from two sources:
1. YDK_COMPONENTS_ADAPTER — explicit adapter definitions (legacy database adapters)
2. YDK_COMPONENTS_CONTRACT + YDK_COMPONENTS_EXT — generates external service adapters
   by matching ext components (technology providers) to contract ports that are NOT
   repository ports.

Output: app/adapters/{tech}/{tech}_adapter.py
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
from _context.naming import derive_name, port_module_name, to_snake
from _context.todos import adapter_todo
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def _normalize_folder(folder: str) -> str:
    """Convert folder name to valid Python package name (underscores, no hyphens)."""
    normalized = folder.replace("-", "_")
    if normalized != folder:
        print(
            f"Warning: folder '{folder}' contains hyphens — using '{normalized}' "
            f"(hyphens are not valid Python package names)",
            file=sys.stderr,
        )
    return normalized


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
    # Entity types need Model suffix to match generated SQLAlchemy class names
    if mapped == t and t and t[0].isupper() and t not in PRIMITIVES and not t.endswith("Model"):
        return f"{t}Model"
    return mapped


def to_snake_smart(name: str) -> str:
    """Smart snake_case for technology names — always produces valid Python identifiers."""
    known = {
        "APScheduler": "apscheduler",
        "YFinance": "yfinance",
        "InMemory": "in_memory",
        "PostgreSQL": "postgresql",
        "SQLAlchemy": "sqlalchemy",
        "Redis": "redis",
        "AlphaVantage": "alpha_vantage",
        "Finnhub": "finnhub",
        "TradingView": "tradingview",
        "Cognito": "cognito",
        "Alpaca": "alpaca",
    }
    if name in known:
        return known[name]
    s = re.sub("([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub("([a-z])([A-Z])", r"\1_\2", s)
    s = s.lower()
    # Replace any non-alphanumeric characters with underscores, collapse multiples
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "adapter"


def _ext_id_to_tech_name(ext_id: str) -> str:
    """Extract technology name from ext component ID.

    "ydk:ext:market-data/yfinance" -> "YFinance"
    "ydk:ext:broker/alpaca" -> "Alpaca"
    "ydk:ext:scheduler/apscheduler" -> "APScheduler"
    "ydk:ext:auth/cognito" -> "Cognito"
    """
    # Get the last segment after /
    if "/" in ext_id:
        slug = ext_id.rsplit("/", 1)[1]
    elif ":" in ext_id:
        slug = ext_id.rsplit(":", 1)[1]
    else:
        slug = ext_id

    # Known mappings for proper casing
    known = {
        "yfinance": "YFinance",
        "alpaca": "Alpaca",
        "apscheduler": "APScheduler",
        "cognito": "Cognito",
        "alpha-vantage": "AlphaVantage",
        "finnhub": "Finnhub",
        "tradingview": "TradingView",
        "redis": "Redis",
        "postgresql": "PostgreSQL",
    }
    if slug.lower() in known:
        return known[slug.lower()]

    # Default: capitalize first letter
    return slug[0].upper() + slug[1:] if slug else "External"


def _ext_id_to_domain(ext_id: str) -> str:
    """Extract the domain/category from an ext component ID.

    "ydk:ext:market-data/yfinance" -> "market-data"
    "ydk:ext:broker/alpaca" -> "broker"
    """
    # Strip ydk:ext: prefix
    stripped = ext_id
    if stripped.startswith("ydk:ext:"):
        stripped = stripped[len("ydk:ext:") :]
    # Get the namespace (before /)
    if "/" in stripped:
        return stripped.split("/", 1)[0]
    return stripped


def build_adapter_context(adapter: dict, ports_map: dict) -> dict:
    """Build the Jinja2 template context for one adapter."""
    name = adapter["name"]
    implements = adapter.get("implements", "")
    port = ports_map.get(implements, {})

    # G4: When adapter implements a port, ALWAYS use port's method signatures.
    # Fall back to adapter-level methods only if no port is found.
    if implements and port:
        methods_raw = port.get("methods", [])
    else:
        methods_raw = adapter.get("methods", [])

    technology = adapter.get("technology", "")
    reference = adapter.get("reference", "")
    description = adapter.get("description", f"Adapter for {implements or name}")

    imports = set()
    if implements:
        module = port_module_name(implements)
        imports.add(f"from app.core.ports.{module} import {implements}")

    methods = []
    for m in methods_raw:
        mname = m["name"]
        returns = map_type(m.get("returns", "None"))
        if "UUID" in returns:
            imports.add("from uuid import UUID")
        if "datetime" in returns:
            imports.add("from datetime import datetime")
        # When methods come from a port, default to async=True to match protocol_ports.
        # Standalone adapter methods (no port) default to sync.
        async_default = True if (implements and port) else False
        is_async = m.get("async", async_default)
        params = []
        for a in m.get("args", []):
            arg_type = a.get("type", "")
            ptype = map_type(arg_type)
            if arg_type and arg_type.strip()[0].isupper():
                raw = arg_type.strip()
                model_cls = raw if raw.endswith("Model") else f"{raw}Model"
                imports.add(f"from app.core.models.{to_snake(raw)} import {model_cls}")
            params.append({"name": a["name"], "type": ptype})

        todo_lines = adapter_todo(name, mname, adapter)
        methods.append(
            {
                "name": mname,
                "is_async": is_async,
                "return_type": returns,
                "params": params,
                "todo_lines": todo_lines,
            }
        )

    init_todo_lines = adapter_todo(name, "__init__", adapter)

    return {
        "name": name,
        "parent_class": implements if implements else "",
        "description": description,
        "technology": technology,
        "reference": reference,
        "imports": sorted(imports),
        "methods": methods,
        "init_todo_lines": init_todo_lines,
    }


def _build_ext_adapter_context(
    ext_component: dict,
    contract_port: dict,
    port_name: str,
) -> dict:
    """Build adapter context from ext component + contract port pair.

    This generates an external service adapter (e.g. YFinanceMarketDataAdapter)
    from the ext component (technology) and the contract port it implements.
    """
    ext_id = ext_component.get("id", "")
    tech_name = _ext_id_to_tech_name(ext_id)
    adapter_name = f"{tech_name}{port_name.removesuffix('Port')}Adapter"

    # Get methods from the contract port
    methods_raw = contract_port.get("methods", {})
    if isinstance(methods_raw, dict):
        methods_list = []
        for mname, mdef in methods_raw.items():
            if not isinstance(mdef, dict):
                mdef = {}
            methods_list.append({"name": mname, **mdef})
        methods_raw = methods_list

    technology = tech_name
    reference = ext_component.get("base_url", "")
    description = ext_component.get("description", f"{tech_name} implementation of {port_name}")

    imports = set()
    module = port_module_name(port_name)
    imports.add(f"from app.core.ports.{module} import {port_name}")

    methods = []
    for m in methods_raw:
        mname = m["name"]
        # Parse return type from the contract method
        returns_raw = m.get("returns", {})
        if isinstance(returns_raw, dict):
            returns_type = returns_raw.get("type", "None")
        else:
            returns_type = str(returns_raw) if returns_raw else "None"
        returns = map_type(returns_type)

        if "UUID" in returns:
            imports.add("from uuid import UUID")
        if "datetime" in returns and "datetime" != returns:
            imports.add("from datetime import datetime")
        if "date" in returns and "datetime" not in returns:
            imports.add("from datetime import date")
        if "Decimal" in returns:
            imports.add("from decimal import Decimal")

        # Parse params from contract method
        params_raw = m.get("params", {})
        params = []
        if isinstance(params_raw, dict):
            for pname, pdef in params_raw.items():
                if isinstance(pdef, dict):
                    ptype = map_type(pdef.get("type", "str"))
                else:
                    ptype = map_type(str(pdef)) if pdef else "str"
                # Import model types (only entity types, not primitives)
                if ptype and ptype[0].isupper() and ptype not in PRIMITIVES and ptype.endswith("Model"):
                    raw_name = ptype.removesuffix("Model")
                    imports.add(f"from app.core.models.{to_snake(raw_name)} import {ptype}")
                if "Decimal" in ptype:
                    imports.add("from decimal import Decimal")
                if "UUID" in ptype:
                    imports.add("from uuid import UUID")
                if ptype == "date" or ("date" in ptype and "datetime" not in ptype):
                    imports.add("from datetime import date")
                if "datetime" in ptype:
                    imports.add("from datetime import datetime")
                params.append({"name": pname, "type": ptype})
        elif isinstance(params_raw, list):
            for a in params_raw:
                ptype = map_type(a.get("type", "str"))
                params.append({"name": a["name"], "type": ptype})

        # Import model types from return type (only entity types, not stdlib)
        entity_names = re.findall(r"\b([A-Z][A-Za-z0-9]+Model)\b", returns)
        for model_cls in entity_names:
            if model_cls not in PRIMITIVES:
                raw_name = model_cls.removesuffix("Model")
                imports.add(f"from app.core.models.{to_snake(raw_name)} import {model_cls}")

        # Build adapter spec dict for todo generation
        adapter_spec = {
            "technology": technology,
            "implements": port_name,
            "reference": reference,
        }
        todo_lines = adapter_todo(adapter_name, mname, adapter_spec)
        methods.append(
            {
                "name": mname,
                "is_async": True,  # External adapters default to async
                "return_type": returns,
                "params": params,
                "todo_lines": todo_lines,
            }
        )

    adapter_spec = {
        "technology": technology,
        "implements": port_name,
        "reference": reference,
    }
    init_todo_lines = adapter_todo(adapter_name, "__init__", adapter_spec)

    return {
        "name": adapter_name,
        "parent_class": port_name,
        "description": description.strip().split("\n")[0][:120] if description else f"{tech_name} adapter",
        "technology": technology,
        "reference": reference,
        "imports": sorted(imports),
        "methods": methods,
        "init_todo_lines": init_todo_lines,
    }


def _match_ext_to_ports(
    ext_components: list[dict],
    contract_ports: dict[str, dict],
) -> list[tuple[dict, dict, str]]:
    """Match ext components to contract ports by domain affinity.

    Returns list of (ext_component, contract_port, port_name) tuples.

    Matching strategy:
    - ext domain "market-data" matches ports containing "MarketData" or "market_data"
    - ext domain "broker" matches ports containing "Broker"
    - ext domain "scheduler" matches ports containing "Scheduler"
    - ext domain "auth" matches ports containing "Auth"
    - ext domain "notifications" matches ports containing "Notification"
    - ext domain "agent" matches ports containing "Agent"
    - ext domain "event-bus" matches ports containing "EventBus" or "event_bus"
    """
    matches: list[tuple[dict, dict, str]] = []

    for ext in ext_components:
        ext_id = ext.get("id", "")
        domain = _ext_id_to_domain(ext_id)
        domain_normalized = domain.replace("-", "_").lower()

        # Find matching ports by domain
        for port_name, port_def in contract_ports.items():
            port_lower = port_name.lower()
            port_snake = to_snake(port_name).lower()

            # Match by domain: market-data -> market_data_port, broker -> broker_port, etc.
            if domain_normalized in port_snake or domain_normalized.replace("_", "") in port_lower.replace("_", ""):
                matches.append((ext, port_def, port_name))
                break  # Each ext matches at most one port

    return matches


def main() -> None:
    adapters_path = os.environ.get("YDK_COMPONENTS_ADAPTER", "")
    ports_path = os.environ.get("YDK_COMPONENTS_CONTRACT", "")
    ext_path = os.environ.get("YDK_COMPONENTS_EXT", "")

    # Set up Jinja2
    templates_dir = Path(__file__).parent.parent / "templates" / "adapters"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("adapter_stub.py.j2")

    output = []

    # --- Source 1: Explicit adapter components (legacy/database adapters) ---
    ports_map = {}
    if ports_path and Path(ports_path).exists():
        pdata = yaml.safe_load(Path(ports_path).read_text(encoding="utf-8")) or {}
        contracts_list = pdata if isinstance(pdata, list) else []
        all_ports = [port for c in contracts_list for port in c.get("ports", [])]
        ports_map = {p["name"]: p for p in all_ports}

    if adapters_path and Path(adapters_path).exists():
        data = yaml.safe_load(Path(adapters_path).read_text(encoding="utf-8")) or {}
        for adapter in data.get("adapters", []):
            context = build_adapter_context(adapter, ports_map)
            content = template.render(**context).rstrip() + "\n"

            # Derive clean filename: strip Adapter/Repository suffix from class name
            cls_name = adapter["name"]
            for sfx in ("Adapter", "Repository", "Service"):
                if cls_name.endswith(sfx):
                    cls_name = cls_name[: -len(sfx)]
                    break
            file_stem = to_snake_smart(cls_name)  # AlpacaAdapter -> alpaca

            # Resolve folder: prefer explicit `folder`, fall back to `module` (legacy),
            # then fall back to `technology`, then output flat (no subdirectory).
            folder = (
                adapter.get("folder", "").strip("/") or adapter.get("module", "").strip("/")  # legacy `module` support
            )
            if not folder:
                tech = adapter.get("technology", "").strip()
                if tech:
                    folder = to_snake_smart(tech)

            # Normalize folder to valid Python package name (replace hyphens with underscores)
            if folder:
                folder = _normalize_folder(folder)

            if folder:
                output_path = f"app/adapters/{folder}/{file_stem}.py"
            else:
                output_path = f"app/adapters/{file_stem}.py"
            output.append({"path": output_path, "content": content})

    # --- Source 2: External service adapters from ext + contract components ---
    if ext_path and Path(ext_path).exists() and ports_path and Path(ports_path).exists():
        ext_data = yaml.safe_load(Path(ext_path).read_text(encoding="utf-8")) or []
        if not isinstance(ext_data, list):
            ext_data = [ext_data]

        # Build a map of port-style contracts: contracts that define external port interfaces
        # These are contracts whose methods don't have repository-style CRUD patterns
        # and whose name ends in "Port"
        contract_data = yaml.safe_load(Path(ports_path).read_text(encoding="utf-8")) or []
        if not isinstance(contract_data, list):
            contract_data = [contract_data]

        # Collect port-like contracts (those whose name ends with "Port")
        external_ports: dict[str, dict] = {}
        for contract in contract_data:
            contract_name = derive_name(contract)
            if contract_name.endswith("Port"):
                external_ports[contract_name] = contract

        # Match ext components to ports
        matches = _match_ext_to_ports(ext_data, external_ports)

        # Generate an adapter for each match
        for ext_comp, port_def, port_name in matches:
            context = _build_ext_adapter_context(ext_comp, port_def, port_name)
            content = template.render(**context).rstrip() + "\n"

            # Output path: app/adapters/{technology}/{tech}_{port_stem}.py
            ext_id = ext_comp.get("id", "")
            tech_name = _ext_id_to_tech_name(ext_id)
            tech_snake = to_snake_smart(tech_name)
            port_stem = to_snake(port_name.removesuffix("Port"))

            folder = tech_snake
            file_stem = f"{tech_snake}_{port_stem}"
            output_path = f"app/adapters/{folder}/{file_stem}.py"
            output.append({"path": output_path, "content": content})

    # Ensure __init__.py exists for every adapter subdirectory
    seen_dirs: set[str] = set()
    init_files: list[dict] = []
    for item in output:
        p = item["path"]
        # e.g. "app/adapters/yfinance/yfinance_market_data.py" → "app/adapters/yfinance"
        parts = p.split("/")
        if len(parts) >= 4 and parts[0] == "app" and parts[1] == "adapters":
            dir_path = "/".join(parts[:3])  # app/adapters/{tech}
            if dir_path not in seen_dirs:
                seen_dirs.add(dir_path)
                init_files.append({"path": f"{dir_path}/__init__.py", "content": ""})
    output.extend(init_files)

    # If neither source produced output, emit empty array
    if not output:
        print("[]")
        return

    print(json.dumps(output))


if __name__ == "__main__":
    main()

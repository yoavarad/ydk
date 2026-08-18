#!/usr/bin/env python3
"""
Generator: fastapi-dependencies
Generate api/dependencies.py -- FastAPI dependency injection container.
Input: adapters.yaml, ports.yaml, services.yaml, data-model.yaml
Output: app/api/dependencies.py
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
from jinja2 import Environment, FileSystemLoader, StrictUndefined

SINGLETON_TECHNOLOGIES = {"inmemory", "in-memory", "apscheduler", "singleton", "in_memory"}


def to_snake_smart(name: str) -> str:
    """Smart snake_case for technology names — always produces valid Python identifiers."""
    known = {
        "APScheduler": "apscheduler",
        "YFinance": "yfinance",
        "InMemory": "in_memory",
        "PostgreSQL": "postgresql",
        "SQLAlchemy": "sqlalchemy",
    }
    if name in known:
        return known[name]
    s = to_snake(name)
    # Replace any non-alphanumeric characters (hyphens, dots, spaces, etc.) with underscores
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "adapter"


def _adapter_module_path(adapter: dict) -> tuple[str, str]:
    """Derive the import path for an adapter — mirrors adapter_stubs.py output path logic."""
    class_name = adapter["name"]

    # Derive file stem from class name (strip common suffixes)
    cls_name = class_name
    for sfx in ("Adapter", "Repository", "Service"):
        if cls_name.endswith(sfx):
            cls_name = cls_name[: -len(sfx)]
            break
    file_stem = to_snake_smart(cls_name)  # AlpacaAdapter → alpaca

    folder = (
        adapter.get("folder", "").strip("/") or adapter.get("module", "").strip("/")  # legacy
    )
    if not folder:
        tech = adapter.get("technology", "").strip()
        if tech:
            folder = to_snake_smart(tech)

    if folder:
        dotpath = folder.replace("/", ".")
        return f"app.adapters.{dotpath}.{file_stem}", class_name
    else:
        return f"app.adapters.{file_stem}", class_name


def build_context(adapters_data: dict, uc_data: dict, dm_data: dict) -> dict:
    """Build the Jinja2 template context for dependencies.py."""
    adapters_raw = adapters_data if isinstance(adapters_data, list) else adapters_data.get("adapters", [])
    uc_list = uc_data if isinstance(uc_data, list) else []
    use_cases = {derive_name(uc): uc for uc in uc_list}
    entities = dm_data if isinstance(dm_data, list) else []

    # Determine session types needed
    async_services = set()
    sync_services = set()
    for uc_name, uc in use_cases.items():
        session_type = uc.get("session_type", "")
        if session_type == "sync":
            sync_services.add(uc_name)
        elif session_type == "async":
            async_services.add(uc_name)
        else:
            methods = uc.get("methods", {})
            if isinstance(methods, dict):
                is_async = any(mdef.get("async", False) for mdef in methods.values() if isinstance(mdef, dict))
            else:
                is_async = any(m.get("async", False) for m in methods)
            if is_async:
                async_services.add(uc_name)
            else:
                sync_services.add(uc_name)

    need_async = bool(async_services) or not use_cases
    need_sync = bool(sync_services)

    # Entity contexts — repo providers always use sync session (safer default)
    entity_contexts = []
    entity_names = set()
    for entity in entities:
        name = derive_name(entity)
        entity_contexts.append({"name": name, "snake_name": to_snake(name)})
        entity_names.add(name)

    # Build adapter contexts — skip standard postgres entity repositories when entities
    # are present (they are handled by the entity loop below to avoid duplicate imports).
    def _is_entity_repo(adapter: dict) -> bool:
        """True if this adapter is a standard Postgres{Entity}Repository handled by entity loop."""
        if not entity_names:
            return False
        aname = adapter.get("name", "")
        tech = adapter.get("technology", "")
        if tech != "postgres":
            return False
        for ename in entity_names:
            if aname == f"Postgres{ename}Repository":
                return True
        return False

    adapters = []
    port_imports = []
    port_names_seen = set()
    port_dep_emitted: set[str] = set()
    for adapter in adapters_raw:
        if _is_entity_repo(adapter):
            # Handled by the entity-based repo provider section — skip to avoid duplicates
            continue
        module_path, class_name = _adapter_module_path(adapter)
        port_name = adapter.get("implements", adapter["name"])
        func_snake = to_snake(adapter["name"])

        technology = adapter.get("technology", "").lower().replace("-", "_").replace(" ", "_")
        is_singleton = technology in {t.replace("-", "_").replace(" ", "_") for t in SINGLETON_TECHNOLOGIES}

        # Only emit XxxPortDep for the first adapter that implements a given port
        emit_port_dep = port_name not in port_dep_emitted
        if emit_port_dep:
            port_dep_emitted.add(port_name)

        adapters.append(
            {
                "module_path": module_path,
                "class_name": class_name,
                "port_name": port_name,
                "func_snake": func_snake,
                "is_singleton": is_singleton,
                "emit_port_dep": emit_port_dep,
            }
        )

        port = adapter.get("implements", "")
        if port and port not in port_names_seen:
            module = port_module_name(port)
            port_imports.append(f"from app.core.ports.{module} import {port}")
            port_names_seen.add(port)

    # Service contexts — wire port dependencies from services.yaml
    uc_contexts = []
    for uc_name, uc in use_cases.items():
        svc_class = uc_name if uc_name.endswith("Service") else f"{uc_name}Service"
        snake_svc = to_snake(svc_class)
        deps = []
        raw_ports = uc.get("ports", [])
        port_names = [p["name"] if isinstance(p, dict) else p for p in raw_ports]
        for port_name in port_names:
            # Derive the repository dep type from the port name
            # e.g. WidgetRepositoryPort -> WidgetRepoDep
            # kwarg must match the service stub __init__ param_name: to_snake(port_name)
            kwarg = to_snake(port_name)
            if port_name.endswith("RepositoryPort"):
                entity_name = port_name[: -len("RepositoryPort")]
                dep_type = f"{entity_name}RepoDep"
                param = to_snake(entity_name) + "_repo"
            else:
                dep_type = f"{port_name}Dep"
                param = to_snake(port_name).replace("_port", "")
            deps.append({"param": param, "dep_type": dep_type, "kwarg": kwarg})
        uc_contexts.append({"svc_class": svc_class, "snake_svc": snake_svc, "deps": deps})

    return {
        "need_async": need_async,
        "need_sync": need_sync,
        # Sort adapters and port_imports alphabetically for ruff I001
        "adapters": sorted(adapters, key=lambda a: a["module_path"]),
        "port_imports": sorted(port_imports),
        "entities": entity_contexts,
        "session_dep": "DbSyncSessionDep",
        "use_cases": uc_contexts,
    }


def _service_domain(svc_class: str) -> str:
    """Extract first word of a service class name as its domain.

    StrategyService  -> strategy
    BacktestService  -> backtest
    LearningService  -> learning
    WidgetService    -> widget
    """
    # Strip Service suffix, then take first CamelCase word
    name = svc_class.removesuffix("Service") if svc_class.endswith("Service") else svc_class
    # Split on CamelCase boundary: StrategyRun → ["Strategy", "Run"]
    parts = re.sub(r"([A-Z][a-z]+)", r" \1", name).split()
    return parts[0].lower() if parts else to_snake(name)


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


def _infer_domain_services_for_di(
    route_data: list[dict],
    entity_data: list[dict],
    existing_service_names: set[str],
) -> list[dict]:
    """Infer domain service DI contexts from routes + entities.

    Returns a list of uc_context dicts compatible with the DI template.
    """
    # Group routes by tag
    groups: dict[str, list] = {}
    for ep in route_data:
        segments = [p for p in ep.get("path", "").split("/") if p and not p.startswith("{")]
        if segments and segments[0] == "api":
            segments = segments[1:]
        raw_tag = segments[0] if segments else "root"
        tag = re.sub(r"[^a-z0-9]+", "_", raw_tag.lower()).strip("_") or "root"
        groups.setdefault(tag, []).append(ep)

    # Build entity index
    entity_index: dict[str, str] = {}
    for entity in entity_data:
        ename = derive_name(entity)
        entity_index[to_snake(ename)] = ename

    inferred = []
    for tag in groups:
        singular = _singularize(tag.replace("_", " ").replace("-", " ").replace(" ", "_"))
        svc_name = _to_camel(singular) + "Service"

        if svc_name in existing_service_names:
            continue

        # Find matching entity
        entity_name = entity_index.get(singular)
        if not entity_name:
            entity_name = entity_index.get(tag)
        if not entity_name:
            for ekey, eval in entity_index.items():
                if ekey == singular or ekey.startswith(singular) or singular.startswith(ekey):
                    entity_name = eval
                    break

        snake_svc = to_snake(svc_name)

        if entity_name:
            port_name = f"{entity_name}RepositoryPort"
            param = to_snake(entity_name) + "_repo"
            dep_type = f"{entity_name}RepoDep"
            kwarg = to_snake(port_name)
            deps = [{"param": param, "dep_type": dep_type, "kwarg": kwarg}]
        else:
            deps = []

        inferred.append(
            {
                "svc_class": svc_name,
                "snake_svc": snake_svc,
                "deps": deps,
            }
        )

    return inferred


def _ext_id_to_tech_name(ext_id: str) -> str:
    """Extract technology name from ext component ID.

    "ydk:ext:market-data/yfinance" -> "YFinance"
    "ydk:ext:broker/alpaca" -> "Alpaca"
    "ydk:ext:scheduler/apscheduler" -> "APScheduler"
    "ydk:ext:auth/cognito" -> "Cognito"
    """
    if "/" in ext_id:
        slug = ext_id.rsplit("/", 1)[1]
    elif ":" in ext_id:
        slug = ext_id.rsplit(":", 1)[1]
    else:
        slug = ext_id

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
    return slug[0].upper() + slug[1:] if slug else "External"


def _ext_id_to_domain(ext_id: str) -> str:
    """Extract the domain/category from an ext component ID.

    "ydk:ext:market-data/yfinance" -> "market-data"
    "ydk:ext:broker/alpaca" -> "broker"
    """
    stripped = ext_id
    if stripped.startswith("ydk:ext:"):
        stripped = stripped[len("ydk:ext:") :]
    if "/" in stripped:
        return stripped.split("/", 1)[0]
    return stripped


def _match_ext_to_port_contracts(
    ext_components: list[dict],
    contracts: list[dict],
) -> list[tuple[dict, dict, str]]:
    """Match ext components to port contracts by domain affinity.

    Returns list of (ext_component, contract, port_name) tuples.
    Only matches the FIRST ext per domain (primary adapter).
    """
    matches: list[tuple[dict, dict, str]] = []
    matched_domains: set[str] = set()

    # Build port index: contract name -> contract dict
    port_contracts: dict[str, dict] = {}
    for contract in contracts:
        cname = derive_name(contract)
        if cname.endswith("Port"):
            port_contracts[cname] = contract

    for ext in ext_components:
        ext_id = ext.get("id", "")
        domain = _ext_id_to_domain(ext_id)
        domain_normalized = domain.replace("-", "_").lower()

        if domain_normalized in matched_domains:
            continue  # Only use first ext per domain

        for port_name, port_def in port_contracts.items():
            port_snake = to_snake(port_name).lower()
            if domain_normalized in port_snake or domain_normalized.replace("_", "") in port_snake.replace("_", ""):
                matches.append((ext, port_def, port_name))
                matched_domains.add(domain_normalized)
                break

    return matches


def _build_port_adapter_contexts(
    ext_components: list[dict],
    contracts: list[dict],
) -> list[dict]:
    """Build adapter contexts for ext-derived port adapters.

    For each ext component matched to a port contract, generates an adapter context
    suitable for the DI template (module_path, class_name, port_name, etc).
    """
    matches = _match_ext_to_port_contracts(ext_components, contracts)
    adapters = []

    for ext_comp, _port_def, port_name in matches:
        ext_id = ext_comp.get("id", "")
        tech_name = _ext_id_to_tech_name(ext_id)
        tech_snake = to_snake_smart(tech_name)
        adapter_name = f"{tech_name}{port_name.removesuffix('Port')}Adapter"
        port_stem = to_snake(port_name.removesuffix("Port"))
        file_stem = f"{tech_snake}_{port_stem}"

        module_path = f"app.adapters.{tech_snake}.{file_stem}"
        func_snake = to_snake(adapter_name)

        technology = tech_snake
        is_singleton = technology in {t.replace("-", "_").replace(" ", "_") for t in SINGLETON_TECHNOLOGIES}

        adapters.append(
            {
                "module_path": module_path,
                "class_name": adapter_name,
                "port_name": port_name,
                "func_snake": func_snake,
                "is_singleton": is_singleton,
                "emit_port_dep": True,
            }
        )

    return adapters


def main() -> None:
    from collections import defaultdict

    adapters_path = os.environ.get("YDK_COMPONENTS_ADAPTER", "")
    uc_path = os.environ.get("YDK_COMPONENTS_CONTRACT", "")
    dm_path = os.environ.get("YDK_COMPONENTS_ENTITY", "")
    route_path = os.environ.get("YDK_COMPONENTS_ROUTE", "")
    ext_path = os.environ.get("YDK_COMPONENTS_EXT", "")

    adata = yaml.safe_load(Path(adapters_path).read_text()) if adapters_path and Path(adapters_path).exists() else {}
    uc_data = yaml.safe_load(Path(uc_path).read_text()) if uc_path and Path(uc_path).exists() else {}
    dm_data = yaml.safe_load(Path(dm_path).read_text()) if dm_path and Path(dm_path).exists() else {}
    ext_data = yaml.safe_load(Path(ext_path).read_text()) if ext_path and Path(ext_path).exists() else []
    if not isinstance(ext_data, list):
        ext_data = [ext_data] if ext_data else []

    # Need at least adapters or entities or ext components to generate DI
    entities = dm_data if isinstance(dm_data, list) else []
    adapters_raw = adata if isinstance(adata, list) else adata.get("adapters", []) if isinstance(adata, dict) else []
    contracts_list = uc_data if isinstance(uc_data, list) else []
    if not adapters_raw and not entities and not ext_data:
        print("[]")
        return

    # Set up Jinja2
    templates_dir = Path(__file__).parent.parent / "templates" / "di"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    context = build_context(adata, uc_data or {}, dm_data or {})

    # --- Inject ext-derived port adapters (e.g. YFinanceMarketDataAdapter) ---
    if ext_data and contracts_list:
        port_adapter_contexts = _build_port_adapter_contexts(ext_data, contracts_list)
        existing_port_names = {a["port_name"] for a in context.get("adapters", [])}
        for pac in port_adapter_contexts:
            if pac["port_name"] not in existing_port_names:
                context["adapters"].append(pac)
                existing_port_names.add(pac["port_name"])
                # Add port import
                module = port_module_name(pac["port_name"])
                port_import = f"from app.core.ports.{module} import {pac['port_name']}"
                if port_import not in context["port_imports"]:
                    context["port_imports"].append(port_import)
        # Re-sort after additions
        context["adapters"] = sorted(context["adapters"], key=lambda a: a["module_path"])
        context["port_imports"] = sorted(context["port_imports"])

    # Wire port service dependencies: for each port contract that is a port service,
    # ensure the use_case context includes the adapter dep so the service gets it injected.
    if ext_data and contracts_list:
        port_adapter_map: dict[str, str] = {}  # port_name -> dep_type (e.g. "MarketDataPortDep")
        for a in context.get("adapters", []):
            if a.get("emit_port_dep"):
                port_adapter_map[a["port_name"]] = f"{a['port_name']}Dep"

        for uc in context.get("use_cases", []):
            svc_class = uc["svc_class"]
            # Port services have class names like MarketDataPortService
            base_name = svc_class.removesuffix("Service") if svc_class.endswith("Service") else svc_class
            if base_name.endswith("Port") and not uc.get("deps"):
                port_name = base_name  # e.g. "MarketDataPort"
                if port_name in port_adapter_map:
                    param = (
                        to_snake(port_name).removesuffix("_port")
                        if to_snake(port_name).endswith("_port")
                        else to_snake(port_name)
                    )
                    # The kwarg must match the service stub __init__ param_name: to_snake(port_name)
                    kwarg = to_snake(port_name)
                    uc["deps"] = [
                        {
                            "param": param,
                            "dep_type": port_adapter_map[port_name],
                            "kwarg": kwarg,
                        }
                    ]

    # Infer domain services from routes + entities (if not already covered by contracts)
    route_data = []
    if route_path and Path(route_path).exists():
        route_data = yaml.safe_load(Path(route_path).read_text()) or []
        if not isinstance(route_data, list):
            route_data = []
    entity_list = dm_data if isinstance(dm_data, list) else []
    if route_data and entity_list:
        existing_names = {uc["svc_class"] for uc in context.get("use_cases", [])}
        inferred_ucs = _infer_domain_services_for_di(route_data, entity_list, existing_names)
        context["use_cases"] = context.get("use_cases", []) + inferred_ucs

    output = []

    # --- adapters.py: all adapter provider functions + Dep aliases ---
    adapters_template = env.get_template("dependencies_adapters.py.j2")
    adapters_content = adapters_template.render(**context).rstrip() + "\n"

    # If adapters.py is likely to exceed 300 lines after ruff formatting and there are
    # entities, split repo providers into a separate _repos.py.
    # Note: ruff format expands the template output by ~25-30%, so trigger at 200 raw lines.
    entities = context.get("entities", [])
    if adapters_content.count("\n") > 200 and entities:
        # Build _repos.py with entity repo providers
        # Determine which session imports are needed for _repos.py
        # Import directly from app.database to avoid circular import with adapters.py
        session_dep = context.get("session_dep", "DbSyncSessionDep")
        need_async = context.get("need_async", False)
        need_sync = context.get("need_sync", False) or session_dep == "DbSyncSessionDep"

        repos_lines = [
            '"""Entity repository providers — split from adapters.py (auto-generated).',
            "",
            "NOTE: Do NOT add 'from __future__ import annotations' to this file.",
            "FastAPI resolves Annotated[X, Depends(Y)] at import time; lazy-string annotations",
            "(PEP 563) prevent FastAPI from seeing the Depends() object inside Annotated.",
            '"""',
            "from typing import Annotated",
            "",
            "from fastapi import Depends",
        ]
        if need_async:
            repos_lines.append("from sqlalchemy.ext.asyncio import AsyncSession")
        if need_sync:
            repos_lines.append("from sqlalchemy.orm import Session")
        repos_lines.append("")
        # Import all repo classes — sorted by module name for ruff I001
        sorted_entities = sorted(entities, key=lambda e: e["snake_name"] + "_repository")
        for entity in sorted_entities:
            snake = entity["snake_name"]
            name = entity["name"]
            repos_lines.append(f"from app.adapters.database.repos.{snake}_repository import Postgres{name}Repository")
        # Import all port interfaces — sorted by module name
        for entity in sorted_entities:
            snake = entity["snake_name"]
            name = entity["name"]
            repos_lines.append(f"from app.core.ports.{snake}_repository import {name}RepositoryPort")
        # Import session factory from app.database (avoids circular import with adapters.py)
        if need_async:
            repos_lines.append("from app.database import get_async_session")
        if need_sync:
            repos_lines.append("from app.database import get_db_sync")
        repos_lines.append("")
        # Define session dep locally (same as adapters.py but avoids the circular import)
        if session_dep == "DbSyncSessionDep":
            repos_lines.append("DbSyncSessionDep = Annotated[Session, Depends(get_db_sync)]")
        else:
            repos_lines.append("DbSessionDep = Annotated[AsyncSession, Depends(get_async_session)]")
        repos_lines.append("")
        repos_lines.append("")
        # Emit provider functions — same sorted order as imports
        for entity in sorted_entities:
            snake = entity["snake_name"]
            name = entity["name"]
            repos_lines.append(f"def get_{snake}_repository(db: {session_dep}) -> {name}RepositoryPort:")
            repos_lines.append(f"    return Postgres{name}Repository(db)")
            repos_lines.append("")
            repos_lines.append(f"{name}RepoDep = Annotated[{name}RepositoryPort, Depends(get_{snake}_repository)]")
            repos_lines.append("")
        repos_content = "\n".join(repos_lines).rstrip() + "\n"
        output.append({"path": "app/api/dependencies/_repos.py", "content": repos_content})

        # Rebuild adapters.py without entity repo providers — pass empty entities to template
        slim_context = dict(context)
        slim_context["entities"] = []
        adapters_content = adapters_template.render(**slim_context).rstrip() + "\n"
        # Insert re-export block INSIDE the import section (before first def/assignment),
        # so E402 is not triggered. Use "X as X" form for intentional re-export (avoids F401).
        # Build two groups: PascalCase Dep aliases and snake_case factory functions.
        # Keeping them in a single sorted list avoids isort I001 violations (ruff
        # wants names sorted case-insensitively within a single import block).
        entity_symbols = []
        for entity in sorted_entities:
            entity_symbols.append(f"{entity['name']}RepoDep")
            entity_symbols.append(f"get_{entity['snake_name']}_repository")
        # Sort case-insensitively to match ruff isort's default (force-sort-within-sections)
        entity_symbols_sorted = sorted(entity_symbols, key=str.lower)
        reexport_lines = ["from ._repos import ("]
        for sym in entity_symbols_sorted:
            reexport_lines.append(f"    {sym} as {sym},")
        reexport_lines.append(")")
        reexport_block = "\n".join(reexport_lines)
        # Find the first non-import line (a blank line followed by def or variable assignment)
        # Insert the re-export block at the end of the imports section.
        # Skip any lines that are inside a docstring.
        lines = adapters_content.splitlines()
        insert_at = len(lines)  # default: end of file
        in_docstring = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Track triple-quote docstring boundaries
            if stripped.startswith('"""') or stripped.startswith("'''"):
                quote = stripped[:3]
                if in_docstring:
                    in_docstring = False
                    continue
                # Check if docstring opens and closes on the same line
                if stripped.count(quote) >= 2:
                    continue
                in_docstring = True
                continue
            if in_docstring:
                continue
            if line.startswith("def ") or (
                line and not line.startswith((" ", "\t", "from ", "import ", "#", '"""', "'''")) and i > 5
            ):
                # Found the first non-import code line — insert before it
                # Walk back to skip blank lines
                insert_at = i
                while insert_at > 0 and not lines[insert_at - 1].strip():
                    insert_at -= 1
                break
        new_lines = lines[:insert_at] + ["", reexport_block, ""] + lines[insert_at:]
        adapters_content = "\n".join(new_lines).rstrip() + "\n"

    output.append({"path": "app/api/dependencies/adapters.py", "content": adapters_content})

    # --- {domain}.py: one per service group ---
    # Group use_cases by domain
    domain_groups: dict[str, list] = defaultdict(list)
    for uc in context.get("use_cases", []):
        domain = _service_domain(uc["svc_class"])
        domain_groups[domain].append(uc)

    svc_template = env.get_template("dependencies_services.py.j2")
    all_svc_symbols: list[str] = []
    for domain, ucs in sorted(domain_groups.items()):
        domain_ctx = dict(context)
        # Sort use_cases by snake_svc so service imports are alphabetical (ruff I001)
        domain_ctx["use_cases"] = sorted(ucs, key=lambda u: u["snake_svc"])
        # Collect all *Dep imports needed by this domain's service provider functions.
        # This includes both XxxRepoDep (repo) and XxxPortDep (port) types.
        repo_dep_imports: list[str] = []
        seen_dep_types: set[str] = set()
        for uc in ucs:
            for dep in uc.get("deps", []):
                dep_type = dep.get("dep_type", "")
                if dep_type.endswith("Dep") and dep_type not in seen_dep_types:
                    seen_dep_types.add(dep_type)
                    repo_dep_imports.append(dep_type)
        domain_ctx["repo_dep_imports"] = sorted(repo_dep_imports)
        content = svc_template.render(**domain_ctx).rstrip() + "\n"
        output.append({"path": f"app/api/dependencies/{domain}.py", "content": content})
        for uc in ucs:
            all_svc_symbols.append(f"get_{uc['snake_svc']}")
            all_svc_symbols.append(f"{uc['svc_class']}Dep")

    # --- __init__.py: re-export everything ---
    adapter_symbols = []
    for adapter in context.get("adapters", []):
        adapter_symbols.append(f"get_{adapter['func_snake']}")
        if adapter.get("emit_port_dep"):
            adapter_symbols.append(f"{adapter['port_name']}Dep")
    # Entity repo symbols
    for entity in context.get("entities", []):
        adapter_symbols.append(f"get_{entity['snake_name']}_repository")
        adapter_symbols.append(f"{entity['name']}RepoDep")
    # Session Dep symbols
    session_symbols = []
    if context.get("need_async"):
        session_symbols.append("DbSessionDep")
    if context.get("need_sync"):
        session_symbols.append("DbSyncSessionDep")

    all_symbols = sorted(adapter_symbols + all_svc_symbols + session_symbols)
    init_lines = ["from __future__ import annotations", ""]
    if adapter_symbols or session_symbols:
        init_lines.append("from .adapters import (")
        # Sort symbols alphabetically so ruff I001 is satisfied
        for sym in sorted(adapter_symbols + session_symbols):
            init_lines.append(f"    {sym},")
        init_lines.append(")")
    for domain in sorted(domain_groups.keys()):
        ucs = domain_groups[domain]
        syms = []
        for uc in ucs:
            syms.append(f"get_{uc['snake_svc']}")
            syms.append(f"{uc['svc_class']}Dep")
        init_lines.append(f"from .{domain} import (")
        # Sort symbols alphabetically so ruff I001 is satisfied
        for sym in sorted(syms):
            init_lines.append(f"    {sym},")
        init_lines.append(")")
    init_lines.append("")
    init_lines.append("__all__ = [")
    for sym in all_symbols:
        init_lines.append(f'    "{sym}",')
    init_lines.append("]")
    init_lines.append("")
    output.append(
        {
            "path": "app/api/dependencies/__init__.py",
            "content": "\n".join(init_lines),
        }
    )

    print(json.dumps(output))


if __name__ == "__main__":
    main()

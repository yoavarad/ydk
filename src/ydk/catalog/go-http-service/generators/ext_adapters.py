#!/usr/bin/env python3
"""Generator: ext-adapters.

One adapter package per supported ydk:ext technology. The technology is the ext id
namespace (ydk:ext:kafka/cluster -> kafka). kafka -> internal/adapters/kafka on franz-go:
a type per ext-backed contract (contract description names the technology) implementing
the contract interface, plus a Consumer when an ext endpoint reads (GET). Bodies are TODOs.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _go_common import (
    TODO_STMT,
    comment,
    contract_methods,
    emit,
    entity_names_by_ns,
    ext_technologies,
    go_ident,
    go_pkg,
    imports_for,
    is_ext_backed,
    load,
    module_path,
    render,
    split_id,
)


def _consume_endpoint(exts: list[dict]) -> dict | None:
    for ext in exts:
        endpoints = ext.get("endpoints") or {}
        for name, spec in endpoints.items() if isinstance(endpoints, dict) else []:
            if isinstance(spec, dict) and str(spec.get("method", "")).upper() == "GET":
                return {"ext_id": ext["id"], "name": name, "description": comment(spec.get("description"))}
    return None


def main() -> None:
    known = entity_names_by_ns()
    files = []
    for tech in ext_technologies():
        exts = [e for e in load("ext") if split_id(str(e.get("id", "")))[0].lower() == tech]
        contracts, imports = [], set()
        for contract in load("contract"):
            if not is_ext_backed(contract, tech):
                continue
            ns, name = split_id(str(contract.get("id", "")))
            pkg = go_pkg(ns)
            imports.add(f"{module_path()}/internal/{pkg}")
            contracts.append(
                {
                    "id": contract["id"],
                    "name": go_ident(name),
                    "qualified": f"{pkg}.{go_ident(name)}",
                    "methods": contract_methods(contract, known.get(pkg, set()), qualifier=f"{pkg}."),
                }
            )
        consume = _consume_endpoint(exts)
        types = [t for c in contracts for m in c["methods"] for t in m["types"]]
        std_imports = sorted(set(imports_for(types)) | ({"context"} if consume else set()))
        content = render(
            f"adapters/{tech}.go.j2",
            ext_ids=", ".join(str(e["id"]) for e in exts),
            contracts=contracts,
            domain_imports=sorted(imports),
            consume=consume,
            std_imports=std_imports,
            todo=TODO_STMT,
        )
        files.append({"path": f"internal/adapters/{tech}/{tech}.go", "content": content})
    emit(files)


if __name__ == "__main__":
    main()

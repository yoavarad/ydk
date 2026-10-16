#!/usr/bin/env python3
"""Generator: ext-adapters.

One adapter package per supported ydk:ext technology. The technology is the ext id
namespace (ydk:ext:kafka/cluster -> kafka); it is supported when templates/adapters/<tech>.go.j2
exists. The template gets a type per ext-backed contract (its ext_ref names an ext of the
technology; a description naming it is the deprecated fallback) plus a Consumer when an ext
endpoint reads (GET); bodies are TODOs. kafka renders internal/adapters/kafka on franz-go,
with Connect() building the client main.go wires into the adapters. An unsupported
technology emits a warning naming the ext manifest; domain-packages still generates its port
interfaces and fakes so the service compiles.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _go_common import (
    TODO_STMT,
    check_unique,
    comment,
    contract_methods,
    contract_tech,
    emit,
    entity_names_by_ns,
    ext_tech,
    ext_technologies,
    go_ident,
    go_pkg,
    imports_for,
    load,
    module_path,
    render,
    split_id,
    supported_ext_technologies,
    warn,
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
    supported = supported_ext_technologies()
    files = []
    for ext in load("ext"):
        tech = ext_tech(ext)
        if tech and tech not in supported:
            warn(
                f"{ext.get('id')} uses ext technology {tech!r} with no adapter template "
                f"(templates/adapters/{tech}.go.j2); generating the port interface and fake only"
            )
    for tech in [t for t in ext_technologies() if t in supported]:
        exts = [e for e in load("ext") if ext_tech(e) == tech]
        contracts, imports = [], set()
        for contract in load("contract"):
            if contract_tech(contract) != tech:
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
        entries = [("NewClient", "the pack's client constructor"), ("Connect", "the pack's client constructor")]
        if consume:
            entries += [(n, f"the consumer for {consume['ext_id']}") for n in ("Consumer", "NewConsumer")]
        for c in contracts:
            entries += [(c["name"], c["id"]), ("New" + c["name"], c["id"])]
        check_unique(f"package internal/adapters/{tech}", entries)
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

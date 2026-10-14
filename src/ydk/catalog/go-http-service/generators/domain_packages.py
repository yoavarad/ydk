#!/usr/bin/env python3
"""Generator: domain-packages.

internal/<ns>: entity structs, contract interfaces, TODO stubs, sentinel errors,
and fakes for contracts backed by an ext technology.
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
    emit,
    entity_names_by_ns,
    ext_technologies,
    go_ident,
    go_pkg,
    go_string,
    go_type,
    imports_for,
    is_ext_backed,
    load,
    message,
    render,
    split_id,
)


def _entities(known: dict[str, set[str]]) -> dict[str, list[dict]]:
    by_pkg: dict[str, list[dict]] = {}
    for entity in load("entity"):
        ns, name = split_id(str(entity.get("id", "")))
        pkg = go_pkg(ns)
        fields = []
        raw_fields = entity.get("fields") or {}
        for fname, spec in raw_fields.items() if isinstance(raw_fields, dict) else []:
            if "." in str(fname):  # nested sub-field (e.g. value.user), documented on its parent
                continue
            spec = spec if isinstance(spec, dict) else {}
            fields.append(
                {
                    "name": go_ident(str(fname)),
                    "json": str(fname),
                    "type": go_type(spec.get("type"), known.get(pkg, set())),
                    "description": comment(spec.get("description"), 100),
                }
            )
        by_pkg.setdefault(pkg, []).append(
            {
                "id": entity["id"],
                "name": go_ident(name),
                "description": comment(entity.get("description")),
                "fields": fields,
            }
        )
    return by_pkg


def _raises(contract: dict) -> list[str]:
    methods = contract.get("methods") or {}
    refs: list[str] = []
    for spec in methods.values() if isinstance(methods, dict) else []:
        if isinstance(spec, dict):
            refs.extend(str(r) for r in spec.get("raises") or [])
    return refs


def _contracts(known: dict[str, set[str]]) -> dict[str, list[dict]]:
    by_pkg: dict[str, list[dict]] = {}
    for contract in load("contract"):
        ns, name = split_id(str(contract.get("id", "")))
        pkg = go_pkg(ns)
        ident = go_ident(name)
        by_pkg.setdefault(pkg, []).append(
            {
                "id": contract["id"],
                "name": ident,
                "stub": ident[:1].lower() + ident[1:] + "Stub",
                "description": comment(contract.get("description")),
                "methods": contract_methods(contract, known.get(pkg, set())),
                "raises": _raises(contract),
                "raw": contract,
            }
        )
    return by_pkg


def _errors(packages: set[str], contracts: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Sentinels go in each raising contract's package and in the error's own namespace package."""
    by_id = {str(e.get("id")): e for e in load("error")}
    placed: dict[str, dict[str, dict]] = {}
    for pkg, items in contracts.items():
        for c in items:
            for ref in c["raises"]:
                if ref in by_id:
                    placed.setdefault(pkg, {})[ref] = by_id[ref]
    for err_id, err in by_id.items():
        pkg = go_pkg(split_id(err_id)[0])
        if pkg in packages:
            placed.setdefault(pkg, {})[err_id] = err
    return {
        pkg: [
            {
                "id": err_id,
                "name": "Err" + go_ident(split_id(err_id)[1]),
                "code": str(err.get("code", "")),
                "message": go_string(message(err.get("detail_template") or err.get("description"))),
            }
            for err_id, err in sorted(errs.items())
        ]
        for pkg, errs in placed.items()
    }


def _contract_files(pkg: str, items: list[dict], techs: list[str]) -> list[dict]:
    base = f"internal/{pkg}"
    imports = imports_for([t for c in items for m in c["methods"] for t in m["types"]])
    ctx = {"pkg": pkg, "contracts": items, "imports": imports, "todo": TODO_STMT}
    files = [
        {"path": f"{base}/contracts.go", "content": render("domain/contracts.go.j2", **ctx)},
        {"path": f"{base}/stubs.go", "content": render("domain/stubs.go.j2", **ctx)},
    ]
    backed = [c for c in items if any(is_ext_backed(c["raw"], t) for t in techs)]
    if backed:
        imports = imports_for([t for c in backed for m in c["methods"] for t in m["types"]])
        content = render("domain/fakes.go.j2", pkg=pkg, contracts=backed, imports=imports)
        files.append({"path": f"{base}/fakes.go", "content": content})
    return files


def _check_names(pkg: str, entities: list[dict], contracts: list[dict], errors: list[dict], techs: list[str]) -> None:
    """Fail on any Go identifier generated twice in one package, struct or interface."""
    entries: list[tuple[str, str]] = []
    for e in entities:
        entries.append((e["name"], e["id"]))
        check_unique(f"struct {e['name']} ({e['id']})", [(f["name"], f"field {f['json']!r}") for f in e["fields"]])
    for c in contracts:
        entries += [(c["name"], c["id"]), ("New" + c["name"], c["id"]), (c["stub"], c["id"])]
        if any(is_ext_backed(c["raw"], t) for t in techs):
            entries.append(("Fake" + c["name"], c["id"]))
        check_unique(
            f"interface {c['name']} ({c['id']})", [(m["name"], f"method {m['raw_name']!r}") for m in c["methods"]]
        )
    entries += [(e["name"], e["id"]) for e in errors]
    check_unique(f"package internal/{pkg}", entries)


def main() -> None:
    known = entity_names_by_ns()
    entities = _entities(known)
    contracts = _contracts(known)
    errors = _errors(set(entities) | set(contracts), contracts)
    techs = ext_technologies()
    for pkg in sorted(set(entities) | set(contracts) | set(errors)):
        _check_names(pkg, entities.get(pkg, []), contracts.get(pkg, []), errors.get(pkg, []), techs)
    files = []
    for pkg in sorted(set(entities) | set(contracts) | set(errors)):
        if pkg in entities:
            types = [f["type"] for e in entities[pkg] for f in e["fields"]]
            content = render("domain/types.go.j2", pkg=pkg, entities=entities[pkg], imports=imports_for(types))
            files.append({"path": f"internal/{pkg}/types.go", "content": content})
        if pkg in contracts:
            files.extend(_contract_files(pkg, contracts[pkg], techs))
        if pkg in errors:
            content = render("domain/errors.go.j2", pkg=pkg, errors=errors[pkg])
            files.append({"path": f"internal/{pkg}/errors.go", "content": content})
    emit(files)


if __name__ == "__main__":
    main()

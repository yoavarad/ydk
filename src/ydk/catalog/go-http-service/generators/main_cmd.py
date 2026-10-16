#!/usr/bin/env python3
"""Generator: main-cmd.

cmd/<app>/main.go: env config load, slog JSON logger, http.Server, graceful shutdown on
SIGTERM/SIGINT with the timeout taken from the ydk:nfr tagged shutdown (default 10 s).
A contract bound to an ext (ext_ref) whose technology has an adapter template is wired to
the generated adapter on a client from <tech>adapter.Connect(); every other contract gets
its New<Contract>() stub.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _go_common import (
    app_name,
    contract_tech,
    emit,
    go_ident,
    go_pkg,
    http_port,
    load,
    module_path,
    render,
    split_id,
    supported_ext_technologies,
    tagged,
)

DEFAULT_SHUTDOWN_SECONDS = 10


def shutdown_nfrs(*, report: bool = True) -> list[dict]:
    """ydk:nfr components tagged shutdown (deprecated fallback: id mentions shutdown)."""
    return tagged(load("nfr"), "shutdown", lambda i: "shutdown" in i.lower(), "tags", report=report)


def shutdown_timeout(*, report: bool = True) -> tuple[int, str]:
    """Seconds from the first shutdown nfr whose target has one (e.g. 'exits <= 10 s')."""
    for nfr in shutdown_nfrs(report=report):
        match = re.search(r"(\d+)\s*s\b", str(nfr.get("target", "")))
        if match:
            return int(match.group(1)), str(nfr["id"])
    return DEFAULT_SHUTDOWN_SECONDS, ""


def main() -> None:
    deps, imports, adapters = [], set(), {}
    supported = supported_ext_technologies()
    for contract in load("contract"):
        ns, name = split_id(str(contract.get("id", "")))
        pkg, ident = go_pkg(ns), go_ident(name)
        tech = contract_tech(contract)
        if tech in supported:
            alias = re.sub(r"[^a-z0-9]", "", tech) + "adapter"
            client = alias.removesuffix("adapter") + "Client"
            adapters[tech] = {"alias": alias, "client": client, "path": f"{module_path()}/internal/adapters/{tech}"}
            deps.append({"field": ident, "ctor": f"{alias}.New{ident}({client})"})
        else:
            imports.add(f"{module_path()}/internal/{pkg}")
            deps.append({"field": ident, "ctor": f"{pkg}.New{ident}()"})
    seconds, source = shutdown_timeout()
    app = app_name()
    content = render(
        "cmd/main.go.j2",
        app=app,
        module=module_path(),
        domain_imports=sorted(imports),
        adapters=[adapters[t] for t in sorted(adapters)],
        deps=deps,
        port=http_port(),
        shutdown_seconds=seconds,
        shutdown_source=source,
    )
    emit([{"path": f"cmd/{app}/main.go", "content": content}])


if __name__ == "__main__":
    main()

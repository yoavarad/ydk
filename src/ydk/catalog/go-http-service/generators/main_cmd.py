#!/usr/bin/env python3
"""Generator: main-cmd.

cmd/<app>/main.go: env config load, slog JSON logger, http.Server, graceful shutdown on
SIGTERM/SIGINT with the timeout taken from a shutdown ydk:nfr target (default 10 s).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _go_common import app_name, emit, go_ident, go_pkg, http_port, load, module_path, render, split_id

DEFAULT_SHUTDOWN_SECONDS = 10


def shutdown_timeout() -> tuple[int, str]:
    """Seconds from the first nfr whose id mentions shutdown (e.g. 'exits <= 10 s')."""
    for nfr in load("nfr"):
        if "shutdown" not in str(nfr.get("id", "")).lower():
            continue
        match = re.search(r"(\d+)\s*s\b", str(nfr.get("target", "")))
        if match:
            return int(match.group(1)), str(nfr["id"])
    return DEFAULT_SHUTDOWN_SECONDS, ""


def main() -> None:
    deps, imports = [], set()
    for contract in load("contract"):
        ns, name = split_id(str(contract.get("id", "")))
        pkg = go_pkg(ns)
        imports.add(f"{module_path()}/internal/{pkg}")
        deps.append({"field": go_ident(name), "ctor": f"{pkg}.New{go_ident(name)}"})
    seconds, source = shutdown_timeout()
    app = app_name()
    content = render(
        "cmd/main.go.j2",
        app=app,
        module=module_path(),
        domain_imports=sorted(imports),
        deps=deps,
        port=http_port(),
        shutdown_seconds=seconds,
        shutdown_source=source,
    )
    emit([{"path": f"cmd/{app}/main.go", "content": content}])


if __name__ == "__main__":
    main()

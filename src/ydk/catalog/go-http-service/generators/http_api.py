#!/usr/bin/env python3
"""Generator: http-api.

internal/httpapi: ServeMux routes from ydk:route, JSON error helper and messages from
ydk:error (+ ydk:crosscut error-format), panic recovery, JSON 404/405, /healthz and /readyz.
Business handlers are panic TODOs; health, readiness and ydk:page routes are implemented.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _go_common import (
    TODO_STMT,
    comment,
    emit,
    go_ident,
    go_pkg,
    go_string,
    load,
    module_path,
    render,
    split_id,
)
from _go_common import message as full_message

_GENERIC_CODES = {
    404: ("NOT_FOUND",),
    405: ("METHOD_NOT_ALLOWED",),
    500: ("INTERNAL", "INTERNAL_ERROR", "INTERNAL_SERVER_ERROR"),
}
_DEFAULT_MESSAGES = {
    404: ("msgDefaultNotFound", "not found"),
    405: ("msgDefaultMethodNotAllowed", "method ${method} not allowed"),
    500: ("msgDefaultInternalError", "internal error"),
    503: ("msgDefaultNotReady", "not ready"),
}


def _messages() -> tuple[list[dict], dict[str, str]]:
    """Message constants for HTTP errors (status >= 400). Returns (constants, error id -> const name)."""
    consts: list[dict] = []
    by_id: dict[str, str] = {}
    used: set[str] = set()
    for err in load("error"):
        status = err.get("status_code")
        if not isinstance(status, int) or status < 400:
            continue
        ns, name = split_id(str(err.get("id", "")))
        const = "msg" + go_ident(name)
        if const in used:
            const = "msg" + go_ident(ns) + go_ident(name)
        used.add(const)
        message = err.get("detail_template") or err.get("description") or ""
        consts.append(
            {
                "name": const,
                "message": go_string(full_message(message)),
                "id": err["id"],
                "status": status,
                "code": str(err.get("code", "")).upper(),
            }
        )
        by_id[str(err["id"])] = const
    return consts, by_id


def _const_for(status: int, consts: list[dict], *, force_default: bool = False) -> str:
    """Const for a generic status: the error whose code is the generic one (e.g. NOT_FOUND), else the
    only error with that status, else a pack default (appended to consts)."""
    if not force_default:
        same = [c for c in consts if c["status"] == status]
        generic = [c for c in same if c.get("code") in _GENERIC_CODES.get(status, ())]
        if generic or len(same) == 1:
            return (generic or same)[0]["name"]
    for c in consts:
        if c["status"] == status and c["id"] == "default":
            return c["name"]
    name, message = _DEFAULT_MESSAGES[status]
    consts.append({"name": name, "message": go_string(message), "id": "default", "status": status})
    return name


def _unique(name: str, used: set[str]) -> str:
    candidate, n = name, 2
    while candidate in used:
        candidate, n = f"{name}{n}", n + 1
    used.add(candidate)
    return candidate


def _routes(pages: dict[str, str]) -> list[dict]:
    routes: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for route in load("route"):
        method = str(route.get("method", "GET")).upper()
        path = str(route.get("path", "/"))
        if (method, path) in seen:  # ServeMux panics on duplicate patterns; keep the first
            continue
        seen.add((method, path))
        kind = "todo"
        if method == "GET" and path == "/healthz":
            kind = "health"
        elif method == "GET" and path == "/readyz":
            kind = "ready"
        elif method == "GET" and path in pages:
            kind = "page"
        responses = route.get("responses")
        routes.append(
            {
                "id": str(route.get("id", "")),
                "name": split_id(str(route.get("id", "")))[1],
                "method": method,
                "path": path,
                "kind": kind,
                "page_file": go_string(pages.get(path, "")),
                "description": comment(route.get("description")),
                "responses": responses if isinstance(responses, dict) else {},
            }
        )
    synthetic = [("/healthz", "health", "healthz"), ("/readyz", "ready", "readyz")]
    synthetic += [(p, "page", "page-" + f.removesuffix(".html")) for p, f in sorted(pages.items())]
    for path, kind, name in synthetic:
        if ("GET", path) not in seen:
            routes.append(
                {
                    "id": "ydk-go-http-service",
                    "name": name,
                    "method": "GET",
                    "path": path,
                    "kind": kind,
                    "page_file": go_string(pages.get(path, "")),
                    "description": f"{kind} endpoint added by the pack",
                    "responses": {},
                }
            )
    # Health/ready/page handlers claim their natural names first so business routes get the suffix.
    handlers: set[str] = set()
    for r in sorted(routes, key=lambda r: r["kind"] == "todo"):
        r["handler"] = _unique("handle" + go_ident(r["name"]), handlers)
    for r in routes:
        pattern = r["path"] + "{$}" if r["path"].endswith("/") else r["path"]
        r["pattern_lit"] = go_string(f"{r['method']} {pattern}")
    return routes


def _deps() -> tuple[list[dict], list[str]]:
    deps, imports = [], set()
    for contract in load("contract"):
        ns, name = split_id(str(contract.get("id", "")))
        pkg = go_pkg(ns)
        imports.add(f"{module_path()}/internal/{pkg}")
        deps.append({"field": go_ident(name), "type": f"{pkg}.{go_ident(name)}"})
    return deps, sorted(imports)


def _ref(response: object) -> str:
    return str(response.get("ref", "")) if isinstance(response, dict) else ""


def main() -> None:
    pages = {str(p.get("route", "")): split_id(str(p.get("id", "")))[1] + ".html" for p in load("page")}
    pages.pop("", None)
    consts, by_id = _messages()
    routes = _routes(pages)
    ready_ref = next(
        (str(_ref(r["responses"].get("503") or r["responses"].get(503))) for r in routes if r["kind"] == "ready"),
        "",
    )
    msgs = {
        "msg_404": _const_for(404, consts),
        "msg_405": _const_for(405, consts),
        "msg_500": _const_for(500, consts),
        # Readiness uses its own 503 ref; other 503s (e.g. a dependency outage) carry different text.
        "msg_503": by_id.get(ready_ref) or _const_for(503, consts, force_default=True),
    }
    error_format = next(
        (str(c["id"]) for c in load("crosscut") if str(c.get("id", "")).endswith("/error-format")),
        "",
    )
    deps, domain_imports = _deps()
    files = [
        {
            "path": "internal/httpapi/errors.go",
            "content": render("httpapi/errors.go.j2", messages=consts, error_format=error_format),
        },
        {
            "path": "internal/httpapi/server.go",
            "content": render("httpapi/server.go.j2", routes=routes, deps=deps, domain_imports=domain_imports, **msgs),
        },
        {
            "path": "internal/httpapi/handlers.go",
            "content": render(
                "httpapi/handlers.go.j2",
                routes=routes,
                todo=TODO_STMT,
                module=module_path(),
                uses_web=any(r["kind"] == "page" for r in routes),
                **msgs,
            ),
        },
    ]
    emit(files)


if __name__ == "__main__":
    main()

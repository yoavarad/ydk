#!/usr/bin/env python3
"""
Generator: app-factory
Reads app-config.yaml and generates:
  - app/main.py         (FastAPI app factory + CORS + health check)
  - app/config.py       (pydantic-settings)
  - app/database.py     (async + sync SQLAlchemy engine)
  - app/api/middleware/auth.py  (Cognito JWT verification)

Input: app-config.yaml (YDK_COMPONENTS_CONFIG)
Output: app/ directory files
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def load_artifact(env_var: str) -> dict:
    path = os.environ.get(env_var, "")
    if not path or not Path(path).exists():
        print(f"Error: {env_var} not set or file not found", file=sys.stderr)
        sys.exit(1)
    return yaml.safe_load(Path(path).read_text()) or {}


def _normalize_database(db: dict) -> dict:
    """Normalize database config to always have url_env.

    Handles both formats:
      - url_env: DATABASE_URL          (explicit env var name)
      - url: "${DATABASE_URL}"         (env var wrapped in ${...})
      - url: "postgresql+asyncpg://..."  (literal URL — use as-is via url_literal)
    """
    if "url_env" in db:
        return db  # already in expected format
    url = db.get("url", "")
    url_env = "DATABASE_URL"
    if isinstance(url, str) and url.startswith("${") and url.endswith("}"):
        url_env = url[2:-1]  # extract "DATABASE_URL" from "${DATABASE_URL}"
    result = dict(db)
    result["url_env"] = url_env
    result.setdefault("pool_size", 10)
    return result


def _normalize_error_mappings(mappings: list | None) -> list[dict]:
    """Normalize error_mappings entries to ensure all fields are present."""
    if not mappings:
        return []
    result = []
    for entry in mappings:
        if not isinstance(entry, dict):
            continue
        exc = entry.get("exception", "")
        if not exc:
            continue
        result.append(
            {
                "exception": exc,
                "module": entry.get("module", "app.core.errors"),
                "status_code": int(entry.get("status_code", 400)),
                "code": entry.get("code", exc.upper()),
            }
        )
    return result


def build_context(config: dict) -> dict:
    """Build template context from app-config.yaml."""
    auth = config.get("auth") or {}
    provider = auth.get("provider", "none") if isinstance(auth, dict) else "none"
    # Only pass cognito context when auth provider is explicitly 'cognito'
    auth_cognito = auth.get("cognito") if provider == "cognito" else None
    return {
        "app": config.get("app", {"title": "App", "version": "1.0.0"}),
        "auth": auth,
        "auth_provider": provider,
        "auth_cognito": auth_cognito,
        "cors": {
            "allow_origins": config.get("cors", {}).get("allow_origins", ["*"]),
            "allow_credentials": config.get("cors", {}).get("allow_credentials", True),
            "allow_methods": config.get("cors", {}).get("allow_methods", ["*"]),
            "allow_headers": config.get("cors", {}).get("allow_headers", ["*"]),
        },
        "database": _normalize_database(config.get("database") or {}),
        "error_mappings": _normalize_error_mappings(config.get("error_mappings")),
    }


def _build_errors_module(error_mappings: list[dict]) -> str:
    """Generate the app/api/errors.py module with register_error_handlers."""
    lines = [
        "from fastapi import FastAPI, Request",
        "from fastapi.responses import JSONResponse",
        "",
        "",
    ]
    # Import custom exception classes if error_mappings are defined
    modules: set[str] = set()
    for mapping in error_mappings:
        module = mapping.get("module", "app.core.errors")
        modules.add(module)
    for module in sorted(modules):
        # Collect exception names from this module
        exc_names = [m["exception"] for m in error_mappings if m.get("module", "app.core.errors") == module]
        lines.append(f"from {module} import {', '.join(exc_names)}")
    if modules:
        lines.append("")
    lines.append("")
    lines.append("def register_error_handlers(app: FastAPI) -> None:")
    lines.append('    """Register application-wide exception handlers."""')
    # Generate specific handlers for each error mapping
    for mapping in error_mappings:
        exc = mapping["exception"]
        status_code = mapping.get("status_code", 400)
        lines.append("")
        lines.append(f"    @app.exception_handler({exc})")
        lines.append(f"    async def handle_{exc.lower()}(request: Request, exc: {exc}) -> JSONResponse:")
        lines.append(f'        return JSONResponse(status_code={status_code}, content={{"detail": str(exc)}})')
    # Always add a generic handler
    lines.append("")
    lines.append("    @app.exception_handler(Exception)")
    lines.append("    async def generic_handler(request: Request, exc: Exception) -> JSONResponse:")
    lines.append('        return JSONResponse(status_code=500, content={"detail": str(exc)})')
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    config = load_artifact("YDK_COMPONENTS_CONFIG")
    # Ignition wraps singleton components in a list — unwrap if needed
    if isinstance(config, list):
        config = config[0] if config else {}
    context = build_context(config)

    templates_dir = Path(__file__).parent.parent / "templates" / "app"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # Generate app/api/errors.py stub (imported by main.py)
    error_mappings = context.get("error_mappings", [])
    errors_content = _build_errors_module(error_mappings)

    # Generate __init__.py for all source packages so imports work.
    # Note: some of these may also be produced by specialized generators
    # (db_postgres_repos, fastapi_routes) with re-export content. The ignition
    # engine keeps the first occurrence, and since app_factory runs after those
    # generators (manifest order), those richer versions take precedence.
    init_packages = [
        "app",
        "app/core",
        "app/core/models",
        "app/core/ports",
        "app/core/services",
        "app/adapters",
        "app/adapters/database",
        "app/adapters/database/repos",
        "app/api",
        "app/api/routes",
        "app/api/middleware",
    ]

    output = [{"path": f"{pkg}/__init__.py", "content": ""} for pkg in init_packages]

    output.extend(
        [
            {
                "path": "app/main.py",
                "content": env.get_template("main.py.j2").render(**context).rstrip() + "\n",
            },
            {
                "path": "app/config.py",
                "content": env.get_template("config.py.j2").render(**context).rstrip() + "\n",
            },
            {
                "path": "app/database.py",
                "content": env.get_template("database.py.j2").render(**context).rstrip() + "\n",
            },
            {
                "path": "app/api/middleware/auth.py",
                "content": env.get_template("auth_middleware.py.j2").render(**context).rstrip() + "\n",
            },
            {
                "path": "app/api/errors.py",
                "content": errors_content,
            },
        ]
    )

    print(json.dumps(output))


if __name__ == "__main__":
    main()

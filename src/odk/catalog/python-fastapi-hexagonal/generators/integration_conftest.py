#!/usr/bin/env python3
"""
Generator: integration-conftest
Generate tests/integration/api/conftest.py with StaticPool SQLite engine,
JSONB monkey-patch, lru_cache clearing fixture, and TestClient fixture.
Input: data-model.yaml, app-config.yaml
Output: tests/integration/api/conftest.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add generators dir to path for _context imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _context.naming import derive_name, to_snake
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def build_context(dm_data: dict, app_config_data: dict) -> dict:
    """Build Jinja2 template context for integration conftest."""
    entities_raw = dm_data if isinstance(dm_data, list) else []
    entities = [
        {"name": derive_name(e), "snake_name": to_snake(derive_name(e))}
        for e in entities_raw
        if isinstance(e, dict) and (e.get("id") or e.get("name"))
    ]

    # Derive app module from app-config or default
    app_module = "app.main"

    # Detect database engine type from app-config
    # PostgreSQL is the default when any database configuration is present
    # (url_env_var or url field), which is the norm for this template.
    db_config = (app_config_data or {}).get("database", {})
    use_postgres = bool(db_config.get("url_env_var") or db_config.get("url"))

    return {
        "entities": entities,
        "app_module": app_module,
        "use_postgres": use_postgres,
    }


def main() -> None:
    dm_path = os.environ.get("ODK_COMPONENTS_ENTITY", "")
    app_config_path = os.environ.get("ODK_COMPONENTS_CONFIG", "")

    dm_data = yaml.safe_load(Path(dm_path).read_text(encoding="utf-8")) if dm_path and Path(dm_path).exists() else {}
    app_config_data = (
        yaml.safe_load(Path(app_config_path).read_text(encoding="utf-8"))
        if app_config_path and Path(app_config_path).exists()
        else {}
    )
    # Ignition wraps singleton components in a list — unwrap if needed
    if isinstance(app_config_data, list):
        app_config_data = app_config_data[0] if app_config_data else {}

    context = build_context(dm_data or {}, app_config_data or {})

    # Set up Jinja2
    templates_dir = Path(__file__).parent.parent / "templates" / "tests"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("integration_conftest.py.j2")
    content = template.render(**context).rstrip() + "\n"

    print(json.dumps([{"path": "tests/integration/conftest.py", "content": content}]))


if __name__ == "__main__":
    main()

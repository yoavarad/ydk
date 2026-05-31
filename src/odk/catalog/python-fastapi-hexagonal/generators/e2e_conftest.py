#!/usr/bin/env python3
"""
Generator: e2e-conftest
Generate tests/e2e/conftest.py with TRUNCATE RESTART IDENTITY cleanup fixture.
Input: data-model.yaml, app-config.yaml, adapters.yaml
Output: tests/e2e/conftest.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _context.naming import derive_name, to_snake, validate_table_name
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def build_e2e_context(dm_data: dict, app_config_data: dict, adapters_data: dict) -> dict:
    """Build Jinja2 template context for E2E conftest.

    ERR-6: Uses table_name from data-model.yaml (not derived from entity name).
    ERR-9: Emits DI overrides for non-repository (external) adapters.
    """
    entities_raw = dm_data if isinstance(dm_data, list) else []
    entities = []
    for e in entities_raw:
        if isinstance(e, dict) and (e.get("id") or e.get("name")):
            table_name = validate_table_name(e)
            name = derive_name(e)
            entities.append(
                {
                    "name": name,
                    "snake_name": to_snake(name),
                    "table_name": table_name,
                }
            )

    app_module = "app.main"

    # Detect database engine type from app-config
    db_config = (app_config_data or {}).get("database", {})
    use_postgres = bool(db_config.get("url_env_var") or db_config.get("url"))

    # ERR-9: Collect non-repository adapters that need DI overrides in E2E tests.
    # Repository adapters (technology=postgres) are backed by the real test DB,
    # but external adapters (redis, s3, email, etc.) must be stubbed out.
    external_adapters = []
    for adapter in (adapters_data or {}).get("adapters", []):
        tech = (adapter.get("technology") or "").lower()
        if tech == "postgres":
            continue
        port_name = adapter.get("implements", "")
        if not port_name:
            continue
        external_adapters.append(
            {
                "port_name": port_name,
                "adapter_name": adapter["name"],
                "snake_name": to_snake(port_name).replace("_port", ""),
            }
        )

    return {
        "entities": entities,
        "app_module": app_module,
        "use_postgres": use_postgres,
        "external_adapters": external_adapters,
    }


def main() -> None:
    dm_path = os.environ.get("ODK_COMPONENTS_ENTITY", "")
    app_config_path = os.environ.get("ODK_COMPONENTS_CONFIG", "")
    adapters_path = os.environ.get("ODK_COMPONENTS_ADAPTER", "")

    dm_data = yaml.safe_load(Path(dm_path).read_text(encoding="utf-8")) if dm_path and Path(dm_path).exists() else {}
    app_config_data = (
        yaml.safe_load(Path(app_config_path).read_text(encoding="utf-8"))
        if app_config_path and Path(app_config_path).exists()
        else {}
    )
    adapters_data = (
        yaml.safe_load(Path(adapters_path).read_text(encoding="utf-8"))
        if adapters_path and Path(adapters_path).exists()
        else {}
    )

    context = build_e2e_context(dm_data or {}, app_config_data or {}, adapters_data or {})

    templates_dir = Path(__file__).parent.parent / "templates" / "tests"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("e2e_conftest.py.j2")
    content = template.render(**context).rstrip() + "\n"
    print(json.dumps([{"path": "tests/e2e/conftest.py", "content": content}]))


if __name__ == "__main__":
    main()

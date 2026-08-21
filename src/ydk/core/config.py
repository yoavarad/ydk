"""Config loading, validation, and management."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ydk.models.config import YdkConfig

DEFAULT_CONFIG: dict[str, Any] = {
    "project": {
        "name": "my-project",
        "spec_location": "docs/specs",
        "adrs_location": "docs/adrs",
        "research_location": "docs/research",
        "remote": "local",
    },
    "hooks": {"pre_push": {"spec_check": False, "task_check": False}},
    "spec_check": {
        "model": "us.anthropic.claude-sonnet-4-6",
        "timeout": 60,
        "global_timeout": 120,
        "concurrency": 10,
        "results_path": ".ydk/spec-check-results.json",
        "thresholds": {
            "completeness": 8,
            "clarity": 8,
            "architecture": 8,
        },
        "custom": [],
    },
    "task_management": {"dag_validation": True, "coverage_check": True},
    "execution": {
        "max_parallel_agents": 5,
        "task_timeout_minutes": 30,
        "worktree_isolation": True,
    },
}


def load_config(config_path: Path = Path(".ydk/config.yaml")) -> YdkConfig:
    """Load and validate config. Returns defaults if file doesn't exist."""
    if not config_path.is_file():
        return YdkConfig.model_validate(DEFAULT_CONFIG)

    raw = yaml.safe_load(config_path.read_text())
    return YdkConfig.model_validate(raw)


def save_config(config: dict[str, Any], config_path: Path = Path(".ydk/config.yaml")) -> None:
    """Save config dict to YAML."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))


def init_config(
    project_name: str,
    config_path: Path = Path(".ydk/config.yaml"),
    force: bool = False,
    remote: str | None = None,
    stack: str | None = None,
) -> YdkConfig:
    """Initialize .ydk/config.yaml with defaults. Raises if exists and not force."""
    if config_path.is_file() and not force:
        msg = f"Config already exists at {config_path}. Use force=True to overwrite."
        raise FileExistsError(msg)

    project_data = {**DEFAULT_CONFIG["project"], "name": project_name}
    if remote:
        project_data["remote"] = remote

    data: dict[str, Any] = {**DEFAULT_CONFIG, "project": project_data}

    if stack:
        from ydk.core.stacks import get_stack

        stack_def = get_stack(stack)
        project_data["stack"] = stack
        data["project"] = project_data

        # Set enabled verifications
        data["verification"] = {"enabled": stack_def.get("verifications", [])}

        # Apply config overrides
        for key_path, value in stack_def.get("config_overrides", {}).items():
            _set_nested(data, key_path, value)
    else:
        data["project"] = project_data

    save_config(data, config_path)
    return YdkConfig.model_validate(data)


def _set_nested(data: dict[str, Any], key_path: str, value: str | int | float | bool | list[str]) -> None:
    """Set a nested value in a dict using dot notation."""
    keys = key_path.split(".")
    current = data
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value


def get_config_value(
    config: dict[str, Any], key_path: str
) -> str | int | float | bool | dict[str, Any] | list[Any] | None:
    """Get nested value via dot notation: 'spec_check.model'"""
    keys = key_path.split(".")
    current: Any = config
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def set_config_value(config: dict[str, Any], key_path: str, value: str) -> dict[str, Any]:
    """Set nested value via dot notation. Coerces types (JSON, bool, int, float, str). Validates result."""
    coerced = _coerce_value(value)

    keys = key_path.split(".")
    current = config
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]

    # Save old value for rollback
    last_key = keys[-1]
    had_old = last_key in current
    old_value = current.get(last_key)
    current[last_key] = coerced

    # Validate the full config to ensure the change is legal
    try:
        YdkConfig.model_validate(config)
    except ValidationError:
        # Roll back the change
        if had_old:
            current[last_key] = old_value
        else:
            del current[last_key]
        raise

    return config


def _coerce_value(value: str) -> str | int | float | bool | list[Any] | dict[str, Any]:
    """Coerce a string value to JSON, bool, int, float, or leave as str.

    Tries JSON parsing first (to support list/dict values), then falls back
    to scalar coercion.
    """
    import json

    try:
        parsed = json.loads(value)
        if isinstance(parsed, (list, dict)):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value

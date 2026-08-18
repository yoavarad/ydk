"""YDK adapter shim — bridges YDK generator conventions to the YDK ignition protocol.

YDK generators:
  - Read artifacts from YDK_COMPONENTS_* env vars
  - Write files directly to disk via Path.write_text()

YDK ignition generators:
  - Read component data from YDK_COMPONENTS_* env vars (YAML file paths)
  - Read init answers from YDK_INIT_ANSWERS env var (JSON dict)
  - Print JSON array of [{"path": "...", "content": "..."}] to stdout

This adapter:
  1. Reads YDK_COMPONENTS_CONTRACT to build a cli-commands.yaml equivalent dict
  2. Provides a collect() context manager that intercepts file writes and
     returns them as YDK GeneratedFile-compatible dicts
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml


def load_commands_from_ydk_components() -> dict:
    """Assemble a cli-commands.yaml-equivalent dict from YDK component data.

    YDK passes assembled components via YDK_COMPONENTS_<TYPE> env vars,
    each pointing to a YAML file containing a list of component dicts.

    The contract component is expected to carry the CLI command specification
    (groups, auth, app_name, base_url_env).  If not present, falls back to
    a direct cli-commands file path via YDK_CLI_COMMANDS for standalone use.
    """
    # Try contract component first (primary YDK path)
    contract_path = os.environ.get("YDK_COMPONENTS_CONTRACT", "")
    if contract_path and Path(contract_path).exists():
        raw = yaml.safe_load(Path(contract_path).read_text(encoding="utf-8"))
        if isinstance(raw, list) and raw:
            # Contract list — use first contract that has CLI command data
            for contract in raw:
                if isinstance(contract, dict) and "groups" in contract:
                    return contract
            # If no contract has groups, merge them all into one
            return raw[0]
        if isinstance(raw, dict):
            return raw

    # Fallback: direct cli-commands path (for standalone / testing)
    commands_path = os.environ.get("YDK_CLI_COMMANDS", "")
    if commands_path and Path(commands_path).exists():
        return yaml.safe_load(Path(commands_path).read_text(encoding="utf-8"))

    return {}


def load_init_answers() -> dict[str, str]:
    """Load init answers from YDK_INIT_ANSWERS env var."""
    raw = os.environ.get("YDK_INIT_ANSWERS", "{}")
    return json.loads(raw)


def emit(files: list[dict[str, str]]) -> None:
    """Print the YDK-protocol JSON array to stdout."""
    print(json.dumps(files))

"""Tests for the lint-ruff verification plugin's graceful degradation.

Covers: skip (not fail) when ``ruff`` isn't on PATH, e.g. a non-Python
project or a machine where ruff isn't installed (GitHub issue #3).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "lint-ruff" / "check.py"


def _run_check(project_root: Path, path_env: str) -> dict:
    env = dict(os.environ)
    env["PATH"] = path_env
    result = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        input=json.dumps({"project_root": str(project_root)}),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_skips_when_ruff_not_on_path(tmp_path: Path) -> None:
    """When ruff isn't installed, the plugin passes (skips) instead of crashing."""
    data = _run_check(tmp_path, path_env="")
    assert data["passed"] is True
    assert "skipped" in data["output"].lower()
    assert "ruff not found" in data["output"]

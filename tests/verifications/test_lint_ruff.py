"""Tests for the lint-ruff verification plugin's graceful degradation.

Covers: skip (not fail) when ``ruff`` isn't on PATH, e.g. a non-Python
project or a machine where ruff isn't installed (GitHub issue #3).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import types

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "lint-ruff" / "check.py"


def _load_check_module() -> types.ModuleType:
    """Import lint-ruff's check.py as a module for direct testing."""
    spec = importlib.util.spec_from_file_location("lint_ruff_check", CHECK_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


class TestResolveRuff:
    """_resolve_ruff prefers the project's own venv over a PATH lookup."""

    def test_prefers_venv_local_binary_when_present(self, tmp_path: Path) -> None:
        mod = _load_check_module()
        venv_dir = "Scripts" if sys.platform == "win32" else "bin"
        suffix = ".exe" if sys.platform == "win32" else ""
        tool_path = tmp_path / ".venv" / venv_dir / f"ruff{suffix}"
        tool_path.parent.mkdir(parents=True)
        tool_path.write_text("")

        assert mod._resolve_ruff(str(tmp_path)) == str(tool_path)

    def test_falls_back_to_bare_name_when_no_venv(self, tmp_path: Path) -> None:
        mod = _load_check_module()

        assert mod._resolve_ruff(str(tmp_path)) == "ruff"

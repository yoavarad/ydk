"""Tests for the tests-pytest verification plugin's graceful degradation.

Covers: skip (not fail) when ``pytest`` isn't on PATH, and when the project
has no tests/ directory at all — e.g. a non-Python project (GitHub issue #3).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    import types

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "tests-pytest" / "check.py"


def _load_check_module() -> types.ModuleType:
    """Import tests-pytest's check.py as a module for direct testing."""
    spec = importlib.util.spec_from_file_location("tests_pytest_check", CHECK_SCRIPT)
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


def test_skips_when_pytest_not_on_path(tmp_path: Path) -> None:
    """When pytest isn't installed, the plugin passes (skips) instead of crashing."""
    (tmp_path / "tests").mkdir()
    data = _run_check(tmp_path, path_env="")
    assert data["passed"] is True
    assert "pytest not found" in data["output"]


def test_skips_when_no_test_dir(tmp_path: Path) -> None:
    """When the project has no tests/ or test/ directory, the plugin skips instead of erroring."""
    # pytest itself may or may not be resolvable — put a fake one on PATH so
    # we're specifically exercising the "no test directory" branch.
    fake_bin = tmp_path / "fake_bin"
    fake_bin.mkdir()
    fake_pytest = fake_bin / ("pytest.bat" if os.name == "nt" else "pytest")
    fake_pytest.write_text("echo fake pytest\n")
    fake_pytest.chmod(0o755)

    data = _run_check(tmp_path, path_env=str(fake_bin))
    assert data["passed"] is True
    assert "no" in data["output"].lower()
    assert "directory" in data["output"].lower()


class TestResolveTool:
    """_resolve_tool prefers the project's own venv over a PATH lookup."""

    def test_prefers_venv_local_binary_when_present(self, tmp_path: Path) -> None:
        mod = _load_check_module()
        venv_dir = "Scripts" if sys.platform == "win32" else "bin"
        suffix = ".exe" if sys.platform == "win32" else ""
        tool_path = tmp_path / ".venv" / venv_dir / f"pytest{suffix}"
        tool_path.parent.mkdir(parents=True)
        tool_path.write_text("")

        assert mod._resolve_tool(str(tmp_path), "pytest") == str(tool_path)

    def test_falls_back_to_path_when_no_venv(self, tmp_path: Path) -> None:
        mod = _load_check_module()
        with patch("shutil.which", return_value="/usr/bin/pytest"):
            assert mod._resolve_tool(str(tmp_path), "pytest") == "/usr/bin/pytest"

    def test_returns_none_when_not_found_anywhere(self, tmp_path: Path) -> None:
        mod = _load_check_module()
        with patch("shutil.which", return_value=None):
            assert mod._resolve_tool(str(tmp_path), "pytest") is None

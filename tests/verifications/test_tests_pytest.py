"""Tests for the tests-pytest verification plugin's graceful degradation.

Covers: skip (not fail) when ``pytest`` isn't on PATH, and when the project
has no tests/ directory at all — e.g. a non-Python project (GitHub issue #3).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "tests-pytest" / "check.py"


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

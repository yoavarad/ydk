"""Tests for the dotnet-tdd-guard verification plugin.

Covers: staged .cs file with no matching *Tests.cs anywhere fails; a matching
*Tests.cs under a Tests/ directory passes; a staged file already inside a
test project is exempt; and empty/absent staged_files passes (fail open).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "dotnet-tdd-guard" / "check.py"


def _run_check(project_root: Path, config: dict | None = None) -> dict:
    context = {"project_root": str(project_root), "config": config or {}}
    result = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        input=json.dumps(context),
        capture_output=True,
        text=True,
    )
    return {"returncode": result.returncode, "stderr": result.stderr, **json.loads(result.stdout)}


def test_fails_when_no_matching_test_file(tmp_path: Path) -> None:
    """A staged .cs file with no FooTests.cs anywhere in the tree fails."""
    data = _run_check(tmp_path, {"staged_files": ["src/Foo.cs"]})

    assert data["returncode"] == 1, data["stderr"]
    assert data["passed"] is False
    assert "FooTests.cs" in data["output"]
    assert "Foo.cs" in data["output"]


def test_passes_when_matching_test_file_exists_under_tests_dir(tmp_path: Path) -> None:
    """A FooTests.cs found under a Tests/ directory satisfies the guard."""
    tests_dir = tmp_path / "MyApp.Tests"
    tests_dir.mkdir()
    (tests_dir / "FooTests.cs").write_text("")

    data = _run_check(tmp_path, {"staged_files": ["src/Foo.cs"]})

    assert data["returncode"] == 0, data["stderr"]
    assert data["passed"] is True


def test_exempts_file_already_inside_test_project(tmp_path: Path) -> None:
    """A staged file that is itself under a Tests-named directory is exempt."""
    data = _run_check(tmp_path, {"staged_files": ["MyApp.Tests/FooTests.cs"]})

    assert data["returncode"] == 0, data["stderr"]
    assert data["passed"] is True


def test_passes_when_staged_files_empty(tmp_path: Path) -> None:
    """Fail open when staged_files is an empty list."""
    data = _run_check(tmp_path, {"staged_files": []})

    assert data["returncode"] == 0, data["stderr"]
    assert data["passed"] is True


def test_passes_when_staged_files_absent(tmp_path: Path) -> None:
    """Fail open when config has no staged_files key at all."""
    data = _run_check(tmp_path, {})

    assert data["returncode"] == 0, data["stderr"]
    assert data["passed"] is True

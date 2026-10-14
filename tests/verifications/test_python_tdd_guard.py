"""Tests for python-tdd-guard: default behaviour and configurable globs / same-dir-suffix strategy."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "python-tdd-guard" / "check.py"

GO_TDD = {"source_globs": ["**/*.go"], "test_for": "same-dir-suffix", "test_suffix": "_test.go"}


def _run(root: Path, staged: list[str], tdd: dict | None = None) -> dict:
    config: dict = {"staged_files": staged}
    if tdd is not None:
        config["tdd"] = tdd
    r = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        input=json.dumps({"project_root": str(root), "config": config}),
        capture_output=True,
        text=True,
    )
    return {"rc": r.returncode, **json.loads(r.stdout)}


def test_default_missing_test_fails(tmp_path: Path) -> None:
    assert _run(tmp_path, ["src/ydk/foo.py"])["passed"] is False


def test_default_test_found_passes(tmp_path: Path) -> None:
    (tmp_path / "tests" / "x").mkdir(parents=True)
    (tmp_path / "tests/x/test_foo.py").write_text("")
    assert _run(tmp_path, ["src/ydk/foo.py"])["passed"] is True


def test_default_ignores_non_py_and_exempt(tmp_path: Path) -> None:
    assert _run(tmp_path, ["src/a.go", "src/ydk/__init__.py", "lib/x.py"])["passed"] is True


def test_go_missing_test_fails(tmp_path: Path) -> None:
    data = _run(tmp_path, ["internal/store/store.go"], GO_TDD)
    assert data["passed"] is False
    assert data["rc"] == 1
    assert "store_test.go" in data["output"]


def test_go_same_dir_test_passes(tmp_path: Path) -> None:
    (tmp_path / "internal/store").mkdir(parents=True)
    (tmp_path / "internal/store/store_test.go").write_text("")
    assert _run(tmp_path, ["internal/store/store.go"], GO_TDD)["passed"] is True


def test_go_test_files_vendor_and_exempt_skipped(tmp_path: Path) -> None:
    tdd = {**GO_TDD, "test_globs": ["**/*_test.go"], "exempt_globs": ["gen/**"]}
    staged = ["a/b_test.go", "vendor/x/y.go", "gen/z.go"]
    assert _run(tmp_path, staged, tdd)["passed"] is True


def test_vendor_skipped_without_tdd_config(tmp_path: Path) -> None:
    assert _run(tmp_path, ["vendor/x/y.py", "pkg/vendor/z.py"], {})["passed"] is True


def test_source_globs_without_test_globs_still_skips_tests_and_init(tmp_path: Path) -> None:
    tdd = {"source_globs": ["**/*.py"]}
    staged = ["tests/test_x.py", "pkg/conftest.py", "pkg/__init__.py"]
    assert _run(tmp_path, staged, tdd)["passed"] is True

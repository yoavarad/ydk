"""Bundled plugins must report self-skips as detail.status == SKIPPED (not a bare PASS)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PLUGINS = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications"
# pr-body-validation only notes a skipped sub-criterion in details; the check itself still runs.
EXEMPT = {"pr-body-validation"}
SKIP_LITERAL = re.compile(r"""["'](?:SKIP:|[^"'\n]*— skipped)""")


def _run(name: str, project_root: Path, extra: dict | None = None) -> dict:
    ctx = {"project_root": str(project_root), **(extra or {})}
    proc = subprocess.run(
        [sys.executable, str(PLUGINS / name / "check.py")],
        input=json.dumps(ctx),
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.mark.parametrize("name", ["tdd-guard", "tdd-guard-cmd"])
def test_tdd_guard_inactive_is_skipped(tmp_path: Path, name: str) -> None:
    data = _run(name, tmp_path)
    assert data["passed"] is True
    assert data["detail"]["status"] == "SKIPPED"
    assert data["detail"]["skip_reason"] == data["output"]


@pytest.mark.parametrize("name", ["terraform-format", "terraform-security", "terraform-tagging"])
def test_terraform_no_infra_is_skipped(tmp_path: Path, name: str) -> None:
    data = _run(name, tmp_path)
    assert data["passed"] is True
    assert data["output"].startswith("SKIP:")
    assert data["detail"]["status"] == "SKIPPED"
    assert data["detail"]["skip_reason"] == data["output"]


@pytest.mark.parametrize("name", ["lint-ruff", "types-ty"])
def test_no_python_files_changed_is_skipped(tmp_path: Path, name: str) -> None:
    data = _run(name, tmp_path, {"changed_files": ["README.md"]})
    assert data["passed"] is True
    assert data["detail"]["status"] == "SKIPPED"
    assert data["detail"]["skip_reason"] == data["output"]


def test_tests_pytest_no_matching_tests_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    data = _run("tests-pytest", tmp_path, {"changed_files": ["src/nothing.py"], "scope": "scoped"})
    if "No test files match" not in data["output"]:
        pytest.skip("scoped path not reached in this environment (pytest unavailable)")
    assert data["detail"]["status"] == "SKIPPED"
    assert data["detail"]["skip_reason"] == data["output"]


@pytest.mark.parametrize("check", sorted(PLUGINS.glob("*/check.py")), ids=lambda p: p.parent.name)
def test_plugins_with_skip_text_declare_skipped_status(check: Path) -> None:
    """Guard: a plugin that emits 'skipped'/'SKIP:' output text must also set detail.status SKIPPED."""
    source = check.read_text(encoding="utf-8")
    if check.parent.name not in EXEMPT and SKIP_LITERAL.search(source):
        assert "SKIPPED" in source, f"{check.parent.name} emits skip text without detail.status == 'SKIPPED'"

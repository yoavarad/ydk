"""Tests for ydk task quick."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ydk.cli import app
from ydk.models.quickdev import QuickDevContext

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

runner = CliRunner()


@patch("ydk.core.quickdev.QuickDevSetup")
def test_task_quick(mock_cls: MagicMock) -> None:
    """ydk task quick sets up quick dev and exits 0."""
    m = MagicMock()
    m.setup.return_value = QuickDevContext(
        task_id="QD-1",
        branch="b",
        description="d",
        components=[],
        testing_guidance="t",
    )
    mock_cls.return_value = m
    r = runner.invoke(app, ["task", "quick", "fix"])
    assert r.exit_code == 0
    assert "QD-1" in r.output


def _quick_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk"], cwd=root, check=True
    )


def _recorded_base(root: Path) -> str:
    data = json.loads((root / ".ydk" / "active-task.json").read_text(encoding="utf-8"))
    (entry,) = data["tasks"].values()
    return entry["base_branch"]


def test_task_quick_base_option_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _quick_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["task", "quick", "--base", "develop", "fix: thing"])
    assert r.exit_code == 0, r.output
    assert _recorded_base(tmp_path) == "develop"


def test_task_quick_default_base_is_repo_default_branch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _quick_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["task", "quick", "fix: thing"])
    assert r.exit_code == 0, r.output
    assert _recorded_base(tmp_path) == "trunk"

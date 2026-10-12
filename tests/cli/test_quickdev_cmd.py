"""Tests for ydk task quick."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ydk.cli import app
from ydk.models.quickdev import QuickDevContext

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


@patch("ydk.core.quickdev.QuickDevSetup")
def test_task_quick_base_passed_through(mock_cls: MagicMock) -> None:
    """--base is forwarded to QuickDevSetup.setup as base_branch."""
    m = MagicMock()
    m.setup.return_value = QuickDevContext(
        task_id="QD-1", branch="b", description="d", components=[], testing_guidance="t"
    )
    mock_cls.return_value = m
    r = runner.invoke(app, ["task", "quick", "--base", "develop", "fix"])
    assert r.exit_code == 0
    assert m.setup.call_args.kwargs["base_branch"] == "develop"

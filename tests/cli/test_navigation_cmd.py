"""Tests for navigation removal."""

from typer.testing import CliRunner

from ydk.cli import app

runner = CliRunner()


def test_navigate_removed() -> None:
    """ydk status navigate is no longer available."""
    assert runner.invoke(app, ["status", "navigate"]).exit_code != 0

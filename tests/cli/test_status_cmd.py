"""Tests for status removal."""

from typer.testing import CliRunner

from ydk.cli import app

runner = CliRunner()


def test_status_removed() -> None:
    """ydk status is no longer a valid command group."""
    assert runner.invoke(app, ["status"]).exit_code != 0

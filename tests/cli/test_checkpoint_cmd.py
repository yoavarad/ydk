"""Tests for checkpoint removal."""

from typer.testing import CliRunner

from ydk.cli import app

runner = CliRunner()


def test_checkpoint_removed() -> None:
    """ydk checkpoint is no longer a valid command."""
    assert runner.invoke(app, ["checkpoint"]).exit_code != 0

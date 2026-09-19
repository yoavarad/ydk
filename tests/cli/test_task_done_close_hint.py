"""Tests that `ydk task done` points users at `ydk task close`."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ydk.cli.task_cmd import task_app

runner = CliRunner()


def _lifecycle_returning(result: dict) -> MagicMock:
    lc = MagicMock()
    lc.done.return_value = result
    return lc


def test_done_help_mentions_task_close() -> None:
    result = runner.invoke(task_app, ["done", "--help"])
    assert result.exit_code == 0
    assert "ydk task close" in " ".join(result.output.split())


@patch("ydk.cli.task_cmd._build_lifecycle")
def test_done_success_prints_close_hint_after_pr_url(mock_build: MagicMock) -> None:
    mock_build.return_value = _lifecycle_returning(
        {"passed": True, "pr_url": "https://github.com/o/r/pull/9"},
    )
    result = runner.invoke(task_app, ["done", "T-042"])
    assert result.exit_code == 0
    out = " ".join(result.output.split())
    assert "PR created: https://github.com/o/r/pull/9" in out
    assert "ydk task close T-042" in out
    assert out.index("PR created") < out.index("ydk task close T-042")


@patch("ydk.cli.task_cmd._build_lifecycle")
def test_done_failure_omits_close_hint_and_keeps_exit_code(mock_build: MagicMock) -> None:
    mock_build.return_value = _lifecycle_returning({"passed": False, "error": "boom"})
    result = runner.invoke(task_app, ["done", "T-042"])
    assert result.exit_code == 1
    assert "Verification failed" in result.output
    assert "boom" in result.output
    assert "ydk task close" not in result.output

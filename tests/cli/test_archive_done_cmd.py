"""Tests for ydk task archive-done CLI command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ydk.cli import app
from ydk.cli._handoff import HANDOFF_EXIT_CODE
from ydk.core.llm_provider import SubagentHandoff

runner = CliRunner()


def test_task_id_passes_compaction_provider() -> None:
    repo = MagicMock()
    provider = object()
    with (
        patch("ydk.cli.task_cmd._get_repo", return_value=repo),
        patch("ydk.core.llm_provider.get_llm_provider", return_value=provider) as get_provider,
    ):
        result = runner.invoke(app, ["task", "archive-done", "--task-id", "T-1"])
    assert result.exit_code == 0, result.output
    assert get_provider.call_args.kwargs["purpose"] == "compaction"
    repo.compact_task.assert_called_once_with("T-1", llm_provider=provider)


def test_all_done_passes_compaction_provider() -> None:
    repo = MagicMock()
    repo.compact_all_done.return_value = ["T-1", "T-2"]
    provider = object()
    with (
        patch("ydk.cli.task_cmd._get_repo", return_value=repo),
        patch("ydk.core.llm_provider.get_llm_provider", return_value=provider),
    ):
        result = runner.invoke(app, ["task", "archive-done", "--all-done"])
    assert result.exit_code == 0, result.output
    assert "Compacted 2 task(s)" in result.output
    repo.compact_all_done.assert_called_once_with(dry_run=False, llm_provider=provider)


def test_handoff_exits_3() -> None:
    repo = MagicMock()
    repo.compact_task.side_effect = SubagentHandoff([])
    with (
        patch("ydk.cli.task_cmd._get_repo", return_value=repo),
        patch("ydk.core.llm_provider.get_llm_provider", return_value=object()),
    ):
        result = runner.invoke(app, ["task", "archive-done", "--task-id", "T-1"])
    assert result.exit_code == HANDOFF_EXIT_CODE
    assert "YDK-SUBAGENT-REQUESTS:" in result.output


def test_no_args_errors() -> None:
    with patch("ydk.cli.task_cmd._get_repo", return_value=MagicMock()):
        result = runner.invoke(app, ["task", "archive-done"])
    assert result.exit_code == 1

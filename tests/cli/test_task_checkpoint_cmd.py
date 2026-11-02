"""Tests for `ydk task checkpoint`."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ydk.cli import app
from ydk.core.llm_provider import SubagentHandoff
from ydk.models.checkpoint import CheckpointPreview

runner = CliRunner()


def _invoke(lc: MagicMock):
    with (
        patch("ydk.cli.task_cmd._build_lifecycle", return_value=lc),
        patch("ydk.cli.task_cmd._resolve_task_id", side_effect=lambda t: t),
    ):
        return runner.invoke(app, ["task", "checkpoint", "5"])


def test_prints_guide() -> None:
    lc = MagicMock()
    lc.checkpoint.return_value = CheckpointPreview(intent="Does a thing", files_changed=1, insertions=2, deletions=1)
    result = _invoke(lc)
    assert result.exit_code == 0
    assert "Does a thing" in result.output


def test_no_diff_message() -> None:
    lc = MagicMock()
    lc.checkpoint.return_value = None
    result = _invoke(lc)
    assert result.exit_code == 0
    assert "No changes" in result.output


def test_subagent_handoff_exits_3() -> None:
    lc = MagicMock()
    lc.checkpoint.side_effect = SubagentHandoff([Path("/r/a.json")])
    result = _invoke(lc)
    assert result.exit_code == 3
    assert "YDK-SUBAGENT-REQUESTS:" in result.output

"""Tests for task lifecycle CLI commands (start, comment, done, list)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ydk.cli import app
from ydk.models.pm import TaskDetail, TaskSummary

runner = CliRunner()


def _make_lifecycle_mock(passed: bool = True) -> MagicMock:
    """Create a mock TaskLifecycle."""
    lc = MagicMock()
    lc.start.return_value = {"task": TaskDetail(title="Test", id="T-001"), "worktree": "/tmp/wt"}
    lc.done.return_value = {
        "passed": passed,
        "pr_url": "https://github.com/repo/pull/1",
        "report": MagicMock(),
    }
    lc.discover.return_value = "T-002"
    return lc


@patch("ydk.cli.task_cmd._build_lifecycle")
def test_task_comment_exits_0(mock_build: MagicMock) -> None:
    """ydk task comment <id> <msg> exits 0."""
    mock_build.return_value = _make_lifecycle_mock()
    result = runner.invoke(app, ["task", "comment", "T-001", "halfway done"])
    assert result.exit_code == 0
    assert "Comment posted" in result.output


def test_task_list_shows_tasks() -> None:
    """ydk task list shows tasks."""
    mock_repo = MagicMock()
    mock_repo.list_tasks.return_value = [
        TaskSummary(id="T-a1b2c3d4", title="First task", status="open", dependencies_met=True),
        TaskSummary(id="T-e5f6a7b8", title="Second task", status="in-progress", dependencies_met=False),
    ]
    with patch("ydk.repositories.factory.get_task_repository", return_value=mock_repo):
        result = runner.invoke(app, ["task", "list"])
    assert result.exit_code == 0
    assert "T-a1b2c3d4" in result.output
    assert "T-e5f6a7b8" in result.output
    assert "First task" in result.output


@patch("ydk.cli.task_cmd._build_lifecycle")
def test_task_comment_with_plan_exits_0(mock_build: MagicMock) -> None:
    """ydk task comment posts comment and exits 0."""
    mock_build.return_value = _make_lifecycle_mock()
    result = runner.invoke(app, ["task", "comment", "T-001", "Step 1: do stuff"])
    assert result.exit_code == 0
    assert "Comment posted" in result.output


@patch("ydk.cli.task_cmd._build_lifecycle")
def test_task_add_subtask_exits_0(mock_build: MagicMock) -> None:
    """ydk task add-subtask creates new task and exits 0."""
    mock_build.return_value = _make_lifecycle_mock()
    result = runner.invoke(app, ["task", "add-subtask", "T-001", "--title", "Fix edge case"])
    assert result.exit_code == 0
    assert "Added subtask" in result.output


def test_task_tdd_sets_stage() -> None:
    """ydk task tdd sets tdd_stage frontmatter."""
    mock_repo = MagicMock()
    mock_repo.get_task.return_value = TaskDetail(id="T-001", title="Test")
    with patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo):
        result = runner.invoke(app, ["task", "tdd", "T-001", "--stage", "red"])
    assert result.exit_code == 0
    assert "red" in result.output
    mock_repo.update_frontmatter.assert_called_once_with("T-001", {"tdd_stage": "red"})


def test_task_tdd_rejects_invalid() -> None:
    """ydk task tdd rejects invalid stage names."""
    result = runner.invoke(app, ["task", "tdd", "T-001", "--stage", "purple"])
    assert result.exit_code != 0

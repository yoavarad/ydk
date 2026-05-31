"""Tests for odk task commands."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from odk.cli import app
from odk.models.pm import TaskDetail, TaskSummary

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def test_task_validate_dag_valid(tmp_path: Path) -> None:
    """odk task validate-dag exits 0 for a valid DAG."""
    mock_repo = MagicMock()
    t1 = TaskDetail(id="T-001", title="First", status="open", dependencies=[])
    t2 = TaskDetail(id="T-002", title="Second", status="open", dependencies=["T-001"])
    t3 = TaskDetail(id="T-003", title="Third", status="open", dependencies=["T-001"])
    mock_repo.list_tasks.return_value = [
        TaskSummary(id="T-001", title="First", status="open", dependencies_met=True),
        TaskSummary(id="T-002", title="Second", status="open", dependencies_met=True),
        TaskSummary(id="T-003", title="Third", status="open", dependencies_met=True),
    ]
    mock_repo.get_task.side_effect = lambda tid: {"T-001": t1, "T-002": t2, "T-003": t3}[tid]
    with patch("odk.cli.task_cmd._get_repo", return_value=mock_repo):
        result = runner.invoke(app, ["task", "validate-dag"])
    assert result.exit_code == 0
    assert "DAG is valid" in result.output


def test_task_validate_dag_cyclic() -> None:
    """odk task validate-dag exits 1 for a cyclic DAG."""
    mock_repo = MagicMock()
    t1 = TaskDetail(id="T-001", title="First", status="open", dependencies=["T-002"])
    t2 = TaskDetail(id="T-002", title="Second", status="open", dependencies=["T-001"])
    mock_repo.list_tasks.return_value = [
        TaskSummary(id="T-001", title="First", status="open", dependencies_met=True),
        TaskSummary(id="T-002", title="Second", status="open", dependencies_met=True),
    ]
    mock_repo.get_task.side_effect = lambda tid: {"T-001": t1, "T-002": t2}[tid]
    with patch("odk.cli.task_cmd._get_repo", return_value=mock_repo):
        result = runner.invoke(app, ["task", "validate-dag"])
    assert result.exit_code != 0
    assert "FAILED" in result.output


def test_task_validate_dag_no_tasks() -> None:
    """odk task validate-dag with no tasks shows message."""
    mock_repo = MagicMock()
    mock_repo.list_tasks.return_value = []
    with patch("odk.cli.task_cmd._get_repo", return_value=mock_repo):
        result = runner.invoke(app, ["task", "validate-dag"])
    assert result.exit_code == 0
    assert "No tasks found" in result.output

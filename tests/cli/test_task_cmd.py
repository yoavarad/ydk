"""Tests for ydk task commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ydk.cli import app
from ydk.cli.task_cmd import _resolve_task_id
from ydk.models.pm import TaskDetail, TaskSummary

runner = CliRunner()


def test_resolve_task_id_reads_mapping_with_utf8_encoding(tmp_path: Path, monkeypatch) -> None:
    """_resolve_task_id reads .ydk/batch-mapping.json with explicit utf-8 encoding."""
    monkeypatch.chdir(tmp_path)
    ydk_dir = tmp_path / ".ydk"
    ydk_dir.mkdir()
    (ydk_dir / "batch-mapping.json").write_text('{"T-001": "42"}', encoding="utf-8")

    with patch("pathlib.Path.read_text", autospec=True, wraps=Path.read_text) as mock_read_text:
        resolved = _resolve_task_id("T-001")

    assert resolved == "42"
    assert mock_read_text.call_args.kwargs.get("encoding") == "utf-8"


def test_task_validate_dag_valid(tmp_path: Path) -> None:
    """ydk task validate-dag exits 0 for a valid DAG."""
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
    with patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo):
        result = runner.invoke(app, ["task", "validate-dag"])
    assert result.exit_code == 0
    assert "DAG is valid" in result.output


def test_task_validate_dag_cyclic() -> None:
    """ydk task validate-dag exits 1 for a cyclic DAG."""
    mock_repo = MagicMock()
    t1 = TaskDetail(id="T-001", title="First", status="open", dependencies=["T-002"])
    t2 = TaskDetail(id="T-002", title="Second", status="open", dependencies=["T-001"])
    mock_repo.list_tasks.return_value = [
        TaskSummary(id="T-001", title="First", status="open", dependencies_met=True),
        TaskSummary(id="T-002", title="Second", status="open", dependencies_met=True),
    ]
    mock_repo.get_task.side_effect = lambda tid: {"T-001": t1, "T-002": t2}[tid]
    with patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo):
        result = runner.invoke(app, ["task", "validate-dag"])
    assert result.exit_code != 0
    assert "FAILED" in result.output


def test_task_validate_dag_no_tasks() -> None:
    """ydk task validate-dag with no tasks shows message."""
    mock_repo = MagicMock()
    mock_repo.list_tasks.return_value = []
    with patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo):
        result = runner.invoke(app, ["task", "validate-dag"])
    assert result.exit_code == 0
    assert "No tasks found" in result.output

"""Tests for gate CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ydk.cli.task_cmd import task_app
from ydk.models.gate import Gate, GateStatus, GateType
from ydk.models.pm import TaskDetail

runner = CliRunner()


def _task_with_gates(gates=None):
    return TaskDetail(id="T-001", title="Test task", status="open", gates=gates or [])


class TestAddGateCommand:
    @patch("ydk.cli.task_cmd._get_repo")
    def test_add_gate_success(self, mock_get_repo) -> None:
        repo = MagicMock()
        repo.get_task.return_value = _task_with_gates()
        mock_get_repo.return_value = repo
        result = runner.invoke(
            task_app, ["add-gate", "T-001", "--type", "pr-merged", "--config", "pr_url=https://github.com/o/r/pull/1"]
        )
        assert result.exit_code == 0
        assert "Added gate" in result.stdout


class TestCheckGatesCommand:
    @patch("ydk.cli.task_cmd._get_repo")
    def test_check_gates_no_gates(self, mock_get_repo) -> None:
        repo = MagicMock()
        repo.get_task.return_value = _task_with_gates([])
        mock_get_repo.return_value = repo
        result = runner.invoke(task_app, ["check-gates", "T-001"])
        assert result.exit_code == 0
        assert "No gates" in result.stdout

    @patch("ydk.cli.task_cmd._get_repo")
    def test_check_gates_all_resolved(self, mock_get_repo) -> None:
        repo = MagicMock()
        repo.get_task.return_value = _task_with_gates(
            [Gate(id="G-001", type=GateType.HUMAN, description="Approved", status=GateStatus.RESOLVED)]
        )
        mock_get_repo.return_value = repo
        with patch("ydk.core.gate_checker.GateChecker") as mock_cls:
            mock_cls.return_value.check_gate.return_value = GateStatus.RESOLVED
            result = runner.invoke(task_app, ["check-gates", "T-001"])
            assert result.exit_code == 0
            assert "G-001" in result.stdout


class TestResolveGateCommand:
    @patch("ydk.cli.task_cmd._get_repo")
    def test_resolve_gate_success(self, mock_get_repo) -> None:
        repo = MagicMock()
        repo.get_task.return_value = _task_with_gates([Gate(id="G-001", type=GateType.HUMAN, description="Approval")])
        mock_get_repo.return_value = repo
        result = runner.invoke(task_app, ["resolve-gate", "T-001", "G-001"])
        assert result.exit_code == 0
        assert "Resolved gate G-001" in result.stdout

    @patch("ydk.cli.task_cmd._get_repo")
    def test_resolve_gate_not_found(self, mock_get_repo) -> None:
        repo = MagicMock()
        repo.get_task.return_value = _task_with_gates([Gate(id="G-001", type=GateType.HUMAN, description="Approval")])
        mock_get_repo.return_value = repo
        result = runner.invoke(task_app, ["resolve-gate", "T-001", "G-999"])
        assert result.exit_code == 1
        assert "not found" in result.stdout

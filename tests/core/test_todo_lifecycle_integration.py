"""Integration test: task_lifecycle.done() auto-resolves assigned TODOs."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from ydk.core.events import EventBus
from ydk.core.task_lifecycle import TaskLifecycle
from ydk.core.todo_manager import TodoManager
from ydk.models.pm import TaskDetail
from ydk.models.todo import TodoStatus
from ydk.models.verification import CheckResult, VerificationReport


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".ydk").mkdir()
    return tmp_path


@pytest.fixture
def passing_report() -> VerificationReport:
    return VerificationReport(
        all_passed=True,
        timestamp="2026-05-03T00:00:00Z",
        total_duration_seconds=1.1,
        checks=[
            CheckResult(name="ruff", passed=True, output="OK", duration_seconds=0.1),
            CheckResult(name="pytest", passed=True, output="5 passed", duration_seconds=1.0),
        ],
    )


@pytest.fixture
def lifecycle(project: Path, passing_report: VerificationReport) -> TaskLifecycle:
    repo = MagicMock()
    repo.get_task.return_value = TaskDetail(
        id="T-001",
        title="Implement create",
        story_id="S-001",
        status="in-progress",
    )
    repo.check_dependencies.return_value = []

    verifier = MagicMock()
    verifier.run_all = AsyncMock(return_value=passing_report)
    verifier.save_proof.return_value = project / ".ydk" / "proofs" / "T-001" / "proof.json"
    # pr-body-validation "not installed" so the final PR-body gate is a no-op.
    verifier.discover_plugins.return_value = []
    verifier.filter_by_name.return_value = []

    worktree = MagicMock()
    worktree.get_worktree_path.return_value = None

    events = EventBus()

    return TaskLifecycle(
        repo=repo,
        events=events,
        worktree_mgr=worktree,
        verifier=verifier,
        project_root=project,
        worktree_isolation=False,
    )


@patch("shutil.which", return_value=None)
@patch("ydk.core.task_lifecycle.subprocess")
def test_done_auto_resolves_todos(
    mock_subprocess: MagicMock, mock_which: MagicMock, lifecycle: TaskLifecycle, project: Path
) -> None:
    """When task done runs, assigned TODOs whose NotImplementedError is gone get marked done."""
    mock_subprocess.run.return_value = MagicMock(returncode=1, stdout="", stderr="")

    # Set up a TODO assigned to task T-001
    todo_mgr = TodoManager(project)

    # Create a source file that is RESOLVED (no NotImplementedError)
    src = project / "app" / "service.py"
    src.parent.mkdir(parents=True)
    src.write_text("def create(self):\n    return self._repo.save()\n")

    todo_id = todo_mgr.register(file="app/service.py", line=1, method="Service.create")
    todo_mgr.assign(todo_id, "T-001")

    result = lifecycle.done("T-001")

    assert result["passed"] is True
    # The TODO should now be done
    item = todo_mgr.get(todo_id)
    assert item.status == TodoStatus.DONE


@patch("shutil.which", return_value=None)
@patch("ydk.core.task_lifecycle.subprocess")
def test_done_warns_on_unresolved_todos(
    mock_subprocess: MagicMock, mock_which: MagicMock, lifecycle: TaskLifecycle, project: Path
) -> None:
    """When task done runs, TODOs still containing NotImplementedError produce warnings."""
    mock_subprocess.run.return_value = MagicMock(returncode=1, stdout="", stderr="")

    todo_mgr = TodoManager(project)

    # Source file still has NotImplementedError
    src = project / "app" / "service.py"
    src.parent.mkdir(parents=True)
    src.write_text("def create(self):\n    raise NotImplementedError  # YDK-TODO-001: Impl\n")

    todo_id = todo_mgr.register(file="app/service.py", line=2, method="Service.create")
    todo_mgr.assign(todo_id, "T-001")

    result = lifecycle.done("T-001")

    assert result["passed"] is True
    assert "todo_warnings" in result
    assert any("NotImplementedError" in w for w in result["todo_warnings"])

    # TODO should still be open
    item = todo_mgr.get(todo_id)
    assert item.status == TodoStatus.OPEN

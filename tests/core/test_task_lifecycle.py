"""Tests for odk.core.task_lifecycle — TaskLifecycle orchestration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odk.core.events import EventBus
from odk.core.task_lifecycle import TaskLifecycle
from odk.models.pm import DependencyStatus, TaskCreate, TaskDetail
from odk.models.verification import CheckResult, VerificationReport


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock()
    repo.get_task.return_value = TaskDetail(
        id="T-001",
        title="Test task",
        story_id="S-001",
        status="open",
    )
    repo.check_dependencies.return_value = []
    repo.create_task.return_value = TaskDetail(
        id="T-002",
        title="Discovered",
        number=2,
    )
    return repo


@pytest.fixture
def mock_worktree() -> MagicMock:
    wt = MagicMock()
    wt.create.return_value = Path("/tmp/worktree/T-001")
    wt.get_worktree_path.return_value = Path("/tmp/worktree/T-001")
    return wt


@pytest.fixture
def mock_verifier() -> MagicMock:
    v = MagicMock()
    return v


@pytest.fixture
def lifecycle(mock_repo: MagicMock, mock_worktree: MagicMock, mock_verifier: MagicMock) -> TaskLifecycle:
    events = EventBus()
    return TaskLifecycle(
        repo=mock_repo,
        events=events,
        worktree_mgr=mock_worktree,
        verifier=mock_verifier,
        project_root=Path("/tmp/project"),
    )


def test_start_checks_dependencies(lifecycle: TaskLifecycle, mock_repo: MagicMock) -> None:
    """start() calls check_dependencies on the repo."""
    lifecycle.start("T-001")
    mock_repo.check_dependencies.assert_called_once_with("T-001")


def test_start_fails_with_unresolved_deps(lifecycle: TaskLifecycle, mock_repo: MagicMock) -> None:
    """start() raises ValueError when dependencies are not resolved."""
    mock_repo.check_dependencies.return_value = [
        DependencyStatus(task_id="T-000", title="Prereq", resolved=False),
    ]
    with pytest.raises(ValueError, match="Unresolved dependencies"):
        lifecycle.start("T-001")


def test_start_creates_worktree_and_updates_status(
    lifecycle: TaskLifecycle, mock_repo: MagicMock, mock_worktree: MagicMock
) -> None:
    """start() creates worktree, updates status to in-progress, assigns agent."""
    result = lifecycle.start("T-001")

    mock_worktree.create.assert_called_once_with("T-001", "Test task", base_branch=None)
    mock_repo.update_status.assert_called_once_with("T-001", "in-progress")
    mock_repo.assign.assert_called_once_with("T-001", "agent")
    mock_repo.add_label.assert_called_once_with("T-001", "in-progress")
    assert "worktree" in result
    assert "task" in result


def test_plan_posts_comment(lifecycle: TaskLifecycle, mock_repo: MagicMock) -> None:
    """plan() posts an implementation plan comment to the repo."""
    lifecycle.plan("T-001", "Step 1: do stuff")
    mock_repo.add_comment.assert_called_once()
    args = mock_repo.add_comment.call_args
    assert args[0][0] == "T-001"
    assert "Implementation Plan" in args[0][1]
    assert "Step 1: do stuff" in args[0][1]


def test_progress_posts_comment(lifecycle: TaskLifecycle, mock_repo: MagicMock) -> None:
    """progress() posts a progress message comment."""
    lifecycle.progress("T-001", "Halfway done")
    mock_repo.add_comment.assert_called_once_with("T-001", "Halfway done")


def test_block_updates_status_and_labels(lifecycle: TaskLifecycle, mock_repo: MagicMock) -> None:
    """block() updates status, adds blocked label, removes in-progress label."""
    lifecycle.block("T-001", "code", "Tests are broken")

    mock_repo.update_status.assert_called_once_with("T-001", "blocked-by-code")
    mock_repo.add_label.assert_called_once_with("T-001", "blocked-by-code")
    mock_repo.remove_label.assert_called_once_with("T-001", "in-progress")
    mock_repo.add_comment.assert_called_once()
    assert "Blocked (code)" in mock_repo.add_comment.call_args[0][1]


@patch("odk.core.task_lifecycle.subprocess")
def test_done_runs_verifications(
    mock_subprocess: MagicMock,
    lifecycle: TaskLifecycle,
    mock_verifier: MagicMock,
    mock_worktree: MagicMock,
) -> None:
    """done() runs verifier.run_all with pre-push trigger."""
    report = VerificationReport(
        timestamp="2025-01-01T00:00:00Z",
        checks=[CheckResult(name="lint", passed=True, output="ok", duration_seconds=1.0)],
        all_passed=True,
        total_duration_seconds=1.0,
    )
    mock_verifier.run_all = AsyncMock(return_value=report)
    mock_verifier.save_proof.return_value = Path("/tmp/proof.json")
    mock_worktree.get_worktree_path.return_value = None

    result = lifecycle.done("T-001")

    mock_verifier.run_all.assert_called_once_with(
        trigger="pre-push",
        context={"project_root": "/tmp/project", "task_id": "T-001"},
    )
    assert result["passed"] is True


def test_done_fails_when_verification_fails(
    lifecycle: TaskLifecycle, mock_verifier: MagicMock, mock_repo: MagicMock
) -> None:
    """done() returns passed=False when verifications fail."""
    report = VerificationReport(
        timestamp="2025-01-01T00:00:00Z",
        checks=[CheckResult(name="lint", passed=False, output="errors found", duration_seconds=1.0)],
        all_passed=False,
        total_duration_seconds=1.0,
    )
    mock_verifier.run_all = AsyncMock(return_value=report)

    result = lifecycle.done("T-001")

    assert result["passed"] is False
    mock_repo.add_comment.assert_called_once()
    assert "Verification FAILED" in mock_repo.add_comment.call_args[0][1]


@patch("odk.core.task_lifecycle.subprocess")
def test_done_creates_pr_when_verification_passes(
    mock_subprocess: MagicMock,
    lifecycle: TaskLifecycle,
    mock_verifier: MagicMock,
    mock_repo: MagicMock,
    mock_worktree: MagicMock,
) -> None:
    """done() creates PR and posts proof when verifications pass."""
    report = VerificationReport(
        timestamp="2025-01-01T00:00:00Z",
        checks=[CheckResult(name="tests", passed=True, output="ok", duration_seconds=2.0)],
        all_passed=True,
        total_duration_seconds=2.0,
    )
    mock_verifier.run_all = AsyncMock(return_value=report)
    mock_verifier.save_proof.return_value = Path("/tmp/proof.json")
    mock_worktree.get_worktree_path.return_value = None

    result = lifecycle.done("T-001")

    assert result["passed"] is True
    assert "pr_url" in result
    # Should have posted proof comment and updated labels
    mock_repo.remove_label.assert_called_once_with("T-001", "in-progress")
    mock_repo.add_label.assert_called_once_with("T-001", "in-review")


def test_start_fails_when_task_already_in_progress(lifecycle: TaskLifecycle, mock_repo: MagicMock) -> None:
    """start() raises ValueError if task is already in-progress."""
    mock_repo.get_task.return_value = TaskDetail(
        id="T-001",
        title="Test task",
        story_id="S-001",
        status="in-progress",
    )
    with pytest.raises(ValueError, match="already in progress"):
        lifecycle.start("T-001")


@patch("odk.core.task_lifecycle.subprocess")
def test_start_without_worktree_isolation(
    mock_subprocess: MagicMock,
    mock_repo: MagicMock,
    mock_worktree: MagicMock,
    mock_verifier: MagicMock,
) -> None:
    """start() skips worktree creation when worktree_isolation=False."""
    events = EventBus()
    lc = TaskLifecycle(
        repo=mock_repo,
        events=events,
        worktree_mgr=mock_worktree,
        verifier=mock_verifier,
        project_root=Path("/tmp/project"),
        worktree_isolation=False,
    )
    result = lc.start("T-001")
    mock_worktree.create.assert_not_called()
    assert "worktree" in result


@patch("shutil.which", return_value=None)
@patch("odk.core.task_lifecycle.subprocess")
def test_create_pr_returns_local_reference(
    mock_subprocess: MagicMock, mock_which: MagicMock, lifecycle: TaskLifecycle, mock_worktree: MagicMock
) -> None:
    """_create_pr returns a local reference when gh is not available."""
    mock_worktree.get_worktree_path.return_value = None
    url = lifecycle._create_pr("T-001")
    assert url.startswith("local://")
    assert "T-001" in url


def test_discover_creates_new_task_linked_to_parent(lifecycle: TaskLifecycle, mock_repo: MagicMock) -> None:
    """discover() creates a new task with the parent as a dependency."""
    new_id = lifecycle.discover("T-001", "Fix edge case", "Found a bug")

    assert new_id == "T-002"
    mock_repo.create_task.assert_called_once()
    created: TaskCreate = mock_repo.create_task.call_args[0][0]
    assert created.title == "Fix edge case"
    assert "T-001" in created.dependencies
    assert "Discovered from #T-001" in created.description

    # Should comment on the parent task
    mock_repo.add_comment.assert_called_once()
    assert "Discovered" in mock_repo.add_comment.call_args[0][1]


def test_start_with_base_branch(lifecycle: TaskLifecycle, mock_repo: MagicMock, mock_worktree: MagicMock) -> None:
    """start() passes base_branch to worktree manager when provided."""
    lifecycle.start("T-001", base_branch="feature/my-branch")

    mock_worktree.create.assert_called_once_with("T-001", "Test task", base_branch="feature/my-branch")


def test_start_defaults_to_head(lifecycle: TaskLifecycle, mock_repo: MagicMock, mock_worktree: MagicMock) -> None:
    """start() defaults base_branch to None (which means HEAD in worktree manager), not main."""
    lifecycle.start("T-001")

    mock_worktree.create.assert_called_once_with("T-001", "Test task", base_branch=None)


def test_start_force_restarts_stale_task(
    lifecycle: TaskLifecycle, mock_repo: MagicMock, mock_worktree: MagicMock
) -> None:
    """start() with force=True cleans up old worktree and restarts an in-progress task."""
    mock_repo.get_task.return_value = TaskDetail(
        id="T-001",
        title="Test task",
        story_id="S-001",
        status="in-progress",
    )

    result = lifecycle.start("T-001", force=True)

    mock_worktree.cleanup.assert_called_once_with("T-001")
    mock_worktree.create.assert_called_once_with("T-001", "Test task", base_branch=None)
    assert "worktree" in result


@patch("odk.core.task_lifecycle.subprocess")
def test_start_with_base_branch_no_worktree_isolation(
    mock_subprocess: MagicMock,
    mock_repo: MagicMock,
    mock_worktree: MagicMock,
    mock_verifier: MagicMock,
) -> None:
    """start() passes base_branch to git checkout -b when worktree_isolation=False."""
    events = EventBus()
    lc = TaskLifecycle(
        repo=mock_repo,
        events=events,
        worktree_mgr=mock_worktree,
        verifier=mock_verifier,
        project_root=Path("/tmp/project"),
        worktree_isolation=False,
    )
    lc.start("T-001", base_branch="develop")

    # Verify git checkout -b was called with the base branch
    mock_subprocess.run.assert_called_once()
    call_args = mock_subprocess.run.call_args[0][0]
    assert call_args[0] == "git"
    assert call_args[1] == "checkout"
    assert call_args[2] == "-b"
    assert "develop" in call_args


def test_done_skip_plugin_rejects_passing_plugin(lifecycle: TaskLifecycle, mock_verifier: MagicMock) -> None:
    """done() raises ValueError when skip_plugins names a passing plugin."""
    report = VerificationReport(
        timestamp="2025-01-01T00:00:00Z",
        checks=[CheckResult(name="lint", passed=True, output="ok", duration_seconds=1.0)],
        all_passed=True,
        total_duration_seconds=1.0,
    )
    mock_verifier.run_all = AsyncMock(return_value=report)

    with pytest.raises(ValueError, match="Cannot skip plugin 'lint'"):
        lifecycle.done("T-001", skip_plugins=["lint"])


def test_done_skip_plugin_allows_genuinely_failing_plugin(
    lifecycle: TaskLifecycle,
    mock_verifier: MagicMock,
    mock_repo: MagicMock,
    mock_worktree: MagicMock,
) -> None:
    """done() allows skipping a plugin that genuinely fails."""
    report = VerificationReport(
        timestamp="2025-01-01T00:00:00Z",
        checks=[
            CheckResult(name="lint", passed=True, output="ok", duration_seconds=1.0),
            CheckResult(name="flaky-e2e", passed=False, output="timeout", duration_seconds=5.0),
        ],
        all_passed=False,
        total_duration_seconds=6.0,
    )
    mock_verifier.run_all = AsyncMock(return_value=report)
    mock_worktree.get_worktree_path.return_value = None

    result = lifecycle.done("T-001", skip_plugins=["flaky-e2e"])

    # All non-skipped plugins pass, so result should be passed=True
    assert result["passed"] is True


def test_done_skip_plugin_still_fails_if_other_plugins_fail(
    lifecycle: TaskLifecycle,
    mock_verifier: MagicMock,
    mock_repo: MagicMock,
) -> None:
    """done() still fails if non-skipped plugins fail."""
    report = VerificationReport(
        timestamp="2025-01-01T00:00:00Z",
        checks=[
            CheckResult(name="lint", passed=False, output="errors", duration_seconds=1.0),
            CheckResult(name="flaky-e2e", passed=False, output="timeout", duration_seconds=5.0),
        ],
        all_passed=False,
        total_duration_seconds=6.0,
    )
    mock_verifier.run_all = AsyncMock(return_value=report)

    result = lifecycle.done("T-001", skip_plugins=["flaky-e2e"])

    # lint still fails
    assert result["passed"] is False


def test_check_xfail_removed_detects_remaining_markers(
    lifecycle: TaskLifecycle,
    tmp_path: Path,
) -> None:
    """_check_xfail_removed detects xfail markers referencing task's TODOs."""
    # Set up a test file with xfail markers
    test_dir = tmp_path / "tests" / "integration" / "api"
    test_dir.mkdir(parents=True)
    test_file = test_dir / "test_strategies_routes.py"
    test_file.write_text(
        "import pytest\n\n"
        '@pytest.mark.xfail(reason="ODK-TODO-0042: implement StrategyService.create")\n'
        "def test_create_strategy():\n"
        "    pass\n"
    )

    # Override project root
    lifecycle._root = tmp_path

    # Mock TodoManager at its source module
    with patch("odk.core.todo_manager.TodoManager") as mock_todo_cls:
        mock_mgr = MagicMock()
        mock_todo_cls.return_value = mock_mgr
        mock_todo = MagicMock()
        mock_todo.id = "ODK-TODO-0042"
        mock_todo.task_id = "T-001"
        mock_mgr.list_todos.return_value = [mock_todo]

        warnings = lifecycle._check_xfail_removed(
            "T-001",
            ["app/api/routes/strategies.py"],
        )

    assert len(warnings) == 1
    assert "ODK-TODO-0042" in warnings[0]


def test_check_xfail_removed_passes_when_markers_gone(
    lifecycle: TaskLifecycle,
    tmp_path: Path,
) -> None:
    """_check_xfail_removed returns empty when xfail markers are removed."""
    # Set up a test file WITHOUT xfail markers
    test_dir = tmp_path / "tests" / "integration" / "api"
    test_dir.mkdir(parents=True)
    test_file = test_dir / "test_strategies_routes.py"
    test_file.write_text("def test_create_strategy():\n    assert True\n")

    lifecycle._root = tmp_path

    with patch("odk.core.todo_manager.TodoManager") as mock_todo_cls:
        mock_mgr = MagicMock()
        mock_todo_cls.return_value = mock_mgr
        mock_todo = MagicMock()
        mock_todo.id = "ODK-TODO-0042"
        mock_todo.task_id = "T-001"
        mock_mgr.list_todos.return_value = [mock_todo]

        warnings = lifecycle._check_xfail_removed(
            "T-001",
            ["app/api/routes/strategies.py"],
        )

    assert warnings == []


def test_derive_test_files_maps_routes_to_integration(lifecycle: TaskLifecycle) -> None:
    """_derive_test_files maps route files to integration test paths."""
    result = lifecycle._derive_test_files(["app/api/routes/strategies.py"])
    assert "tests/integration/api/test_strategies_routes.py" in result


def test_derive_test_files_maps_services_to_unit(lifecycle: TaskLifecycle) -> None:
    """_derive_test_files maps service files to unit test paths."""
    result = lifecycle._derive_test_files(["app/core/services/strategy_service.py"])
    assert "tests/unit/test_strategy_service.py" in result


@patch("odk.core.task_lifecycle.subprocess")
def test_done_removes_active_task_file(
    mock_subprocess: MagicMock,
    mock_repo: MagicMock,
    mock_worktree: MagicMock,
    mock_verifier: MagicMock,
    tmp_path: Path,
) -> None:
    """odk task done removes .odk/active-task.json after success."""
    events = EventBus()
    lc = TaskLifecycle(
        repo=mock_repo,
        events=events,
        worktree_mgr=mock_worktree,
        verifier=mock_verifier,
        project_root=tmp_path,
    )

    # Create active-task.json (simulating task start)
    odk_dir = tmp_path / ".odk"
    odk_dir.mkdir(parents=True, exist_ok=True)
    active_file = odk_dir / "active-task.json"
    active_file.write_text('{"task_id": "T-001", "base_branch": "main"}')

    report = VerificationReport(
        timestamp="2025-01-01T00:00:00Z",
        checks=[CheckResult(name="lint", passed=True, output="ok", duration_seconds=1.0)],
        all_passed=True,
        total_duration_seconds=1.0,
    )
    mock_verifier.run_all = AsyncMock(return_value=report)
    mock_worktree.get_worktree_path.return_value = None

    result = lc.done("T-001")

    assert result["passed"] is True
    assert not active_file.exists(), "active-task.json should be removed after successful done"

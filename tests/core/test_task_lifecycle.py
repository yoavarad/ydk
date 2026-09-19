"""Tests for ydk.core.task_lifecycle — TaskLifecycle orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ydk.core.events import EventBus
from ydk.core.task_lifecycle import TaskLifecycle
from ydk.core.verifier import Verifier
from ydk.models.pm import DependencyStatus, TaskCreate, TaskDetail
from ydk.models.verification import CheckResult, VerificationReport


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
    # By default, the pr-body-validation plugin is "not installed" so the
    # final PR-body gate in done() is a no-op and existing tests that don't
    # care about it aren't affected. Tests that exercise the gate override
    # discover_plugins/filter_by_name/run_layer explicitly.
    v.discover_plugins.return_value = []
    v.filter_by_name.return_value = []
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


@patch("shutil.which", return_value=None)
@patch("ydk.core.task_lifecycle.subprocess")
def test_done_runs_verifications(
    mock_subprocess: MagicMock,
    mock_which: MagicMock,
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
    mock_subprocess.run.return_value.returncode = 0

    result = lifecycle.done("T-001")

    mock_verifier.run_all.assert_called_once_with(
        trigger="pre-push",
        context={"project_root": str(Path("/tmp/project")), "task_id": "T-001"},
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


@patch("shutil.which", return_value=None)
@patch("ydk.core.task_lifecycle.subprocess")
def test_done_creates_pr_when_verification_passes(
    mock_subprocess: MagicMock,
    mock_which: MagicMock,
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
    mock_subprocess.run.return_value.returncode = 0

    result = lifecycle.done("T-001")

    assert result["passed"] is True
    assert "pr_url" in result
    # Should have posted proof comment and updated labels
    mock_repo.update_status.assert_called_once_with("T-001", "in-review")
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


@patch("ydk.core.task_lifecycle.subprocess")
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
@patch("ydk.core.task_lifecycle.subprocess")
def test_create_pr_returns_local_reference(
    mock_subprocess: MagicMock, mock_which: MagicMock, lifecycle: TaskLifecycle, mock_worktree: MagicMock
) -> None:
    """_create_pr returns a local reference when gh is not available."""
    mock_worktree.get_worktree_path.return_value = None
    mock_subprocess.run.return_value.returncode = 0
    url = lifecycle._create_pr("T-001")
    assert url.startswith("local://")
    assert "T-001" in url


@patch("shutil.which", return_value="/usr/bin/gh")
@patch("ydk.core.task_lifecycle.subprocess")
def test_create_pr_uses_body_file_not_inline_arg(
    mock_subprocess: MagicMock, mock_which: MagicMock, lifecycle: TaskLifecycle, mock_worktree: MagicMock
) -> None:
    """_create_pr passes the body via --body-file, not inline --body.

    A large proof-rich PR body passed as a literal --body argument
    overflows Windows' CreateProcess command-line length limit
    (WinError 206). --body-file writes it to a temp file instead.
    """
    mock_worktree.get_worktree_path.return_value = None
    big_body = "proof output\n" * 5000  # large enough to overflow an inline arg on Windows
    captured_file_content: list[str] = []

    def _run_side_effect(args: list[str], **kwargs: object) -> MagicMock:
        if args[:3] == ["gh", "pr", "create"]:
            body_file_path = args[args.index("--body-file") + 1]
            captured_file_content.append(Path(body_file_path).read_text(encoding="utf-8"))
            return MagicMock(returncode=0, stdout="https://github.com/org/repo/pull/1\n")
        if args[:2] == ["git", "rev-parse"]:
            return MagicMock(returncode=0, stdout="task/T-001\n")
        return MagicMock(returncode=0)  # git push

    mock_subprocess.run.side_effect = _run_side_effect

    url = lifecycle._create_pr("T-001", pr_body_override=big_body)

    assert url == "https://github.com/org/repo/pull/1"
    create_call = next(c for c in mock_subprocess.run.call_args_list if c.args[0][:3] == ["gh", "pr", "create"])
    create_args = create_call.args[0]
    assert "--body" not in create_args
    assert "--body-file" in create_args
    assert captured_file_content == [big_body]
    assert create_call.kwargs.get("encoding") == "utf-8"

    rev_parse_call = next(c for c in mock_subprocess.run.call_args_list if c.args[0][:2] == ["git", "rev-parse"])
    assert rev_parse_call.kwargs.get("encoding") == "utf-8"


@patch("shutil.which", return_value="/usr/bin/gh")
@patch("ydk.core.task_lifecycle.subprocess")
def test_create_pr_raises_when_gh_pr_create_fails(
    mock_subprocess: MagicMock, mock_which: MagicMock, lifecycle: TaskLifecycle, mock_worktree: MagicMock
) -> None:
    """_create_pr raises instead of silently falling back to local:// when
    gh is available but `gh pr create` fails for real (e.g. PR body too long)."""
    mock_worktree.get_worktree_path.return_value = None

    def _run_side_effect(args: list[str], **kwargs: object) -> MagicMock:
        if args[:3] == ["gh", "pr", "create"]:
            return MagicMock(
                returncode=1,
                stdout="",
                stderr="GraphQL: Body is too long (maximum is 65536 characters) (createPullRequest)",
            )
        if args[:2] == ["git", "rev-parse"]:
            return MagicMock(returncode=0, stdout="task/T-001\n")
        return MagicMock(returncode=0)  # git push

    mock_subprocess.run.side_effect = _run_side_effect

    with pytest.raises(RuntimeError) as exc_info:
        lifecycle._create_pr("T-001", pr_body_override="some body")

    message = str(exc_info.value)
    assert "T-001" in message
    assert "Body is too long" in message


@patch("shutil.which", return_value="/usr/bin/gh")
@patch("ydk.core.task_lifecycle.subprocess")
def test_create_pr_raises_when_gh_pr_create_returns_empty_stdout(
    mock_subprocess: MagicMock, mock_which: MagicMock, lifecycle: TaskLifecycle, mock_worktree: MagicMock
) -> None:
    """_create_pr raises when gh pr create exits 0 but prints no URL, rather
    than silently falling back to local://."""
    mock_worktree.get_worktree_path.return_value = None

    def _run_side_effect(args: list[str], **kwargs: object) -> MagicMock:
        if args[:3] == ["gh", "pr", "create"]:
            return MagicMock(returncode=0, stdout="", stderr="")
        if args[:2] == ["git", "rev-parse"]:
            return MagicMock(returncode=0, stdout="task/T-001\n")
        return MagicMock(returncode=0)  # git push

    mock_subprocess.run.side_effect = _run_side_effect

    with pytest.raises(RuntimeError) as exc_info:
        lifecycle._create_pr("T-001", pr_body_override="some body")

    assert "T-001" in str(exc_info.value)


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


@patch("ydk.core.task_lifecycle.subprocess")
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


@patch("ydk.core.task_lifecycle.subprocess")
def test_build_pr_body_uses_utf8_encoding_for_git_diff(
    mock_subprocess: MagicMock, lifecycle: TaskLifecycle, mock_worktree: MagicMock
) -> None:
    """_build_pr_body's git diff subprocess call uses explicit utf-8 encoding."""
    mock_worktree.get_worktree_path.return_value = None
    mock_subprocess.run.return_value = MagicMock(returncode=0, stdout="")

    lifecycle._build_pr_body("T-001")

    diff_call = next(c for c in mock_subprocess.run.call_args_list if c.args[0][:2] == ["git", "diff"])
    assert diff_call.kwargs.get("encoding") == "utf-8"


def test_start_writes_active_task_file_with_utf8_encoding(
    mock_repo: MagicMock, mock_worktree: MagicMock, mock_verifier: MagicMock, tmp_path: Path
) -> None:
    """start() writes .ydk/active-task.json with explicit utf-8 encoding."""
    events = EventBus()
    lc = TaskLifecycle(
        repo=mock_repo,
        events=events,
        worktree_mgr=mock_worktree,
        verifier=mock_verifier,
        project_root=tmp_path,
    )
    with patch.object(Path, "write_text", autospec=True) as mock_write_text:
        lc.start("T-001")
    assert mock_write_text.call_args.kwargs.get("encoding") == "utf-8"


def test_start_migrates_legacy_active_task_file(
    mock_repo: MagicMock, mock_worktree: MagicMock, mock_verifier: MagicMock, tmp_path: Path
) -> None:
    """start() migrates a pre-existing legacy flat {"task_id", "base_branch"}
    active-task.json (from before per-task scoping) into the new per-task
    map instead of silently dropping the other task's entry.
    """
    events = EventBus()
    lc = TaskLifecycle(
        repo=mock_repo,
        events=events,
        worktree_mgr=mock_worktree,
        verifier=mock_verifier,
        project_root=tmp_path,
    )

    ydk_dir = tmp_path / ".ydk"
    ydk_dir.mkdir(parents=True, exist_ok=True)
    active_file = ydk_dir / "active-task.json"
    active_file.write_text('{"task_id": "T-000", "base_branch": "legacy-branch"}', encoding="utf-8")

    lc.start("T-001", base_branch="feature/new")

    data = json.loads(active_file.read_text(encoding="utf-8"))
    assert data["tasks"]["T-000"]["base_branch"] == "legacy-branch"
    assert data["tasks"]["T-001"]["base_branch"] == "feature/new"


def test_write_verified_flag_uses_utf8_encoding(
    mock_repo: MagicMock, mock_worktree: MagicMock, mock_verifier: MagicMock, tmp_path: Path
) -> None:
    """_write_verified_flag writes with explicit utf-8 encoding."""
    events = EventBus()
    lc = TaskLifecycle(
        repo=mock_repo,
        events=events,
        worktree_mgr=mock_worktree,
        verifier=mock_verifier,
        project_root=tmp_path,
    )
    with patch.object(Path, "write_text", autospec=True) as mock_write_text:
        lc._write_verified_flag()
    assert mock_write_text.call_args.kwargs.get("encoding") == "utf-8"


@patch("shutil.which", return_value="/usr/bin/gh")
@patch("ydk.core.task_lifecycle.subprocess")
def test_create_pr_reads_active_task_file_with_utf8_encoding(
    mock_subprocess: MagicMock,
    mock_which: MagicMock,
    mock_repo: MagicMock,
    mock_worktree: MagicMock,
    mock_verifier: MagicMock,
    tmp_path: Path,
) -> None:
    """_create_pr reads .ydk/active-task.json with explicit utf-8 encoding."""
    events = EventBus()
    lc = TaskLifecycle(
        repo=mock_repo,
        events=events,
        worktree_mgr=mock_worktree,
        verifier=mock_verifier,
        project_root=tmp_path,
    )
    mock_worktree.get_worktree_path.return_value = None

    ydk_dir = tmp_path / ".ydk"
    ydk_dir.mkdir(parents=True, exist_ok=True)
    active_file = ydk_dir / "active-task.json"
    active_file.write_text('{"tasks": {"T-001": {"base_branch": "main"}}}', encoding="utf-8")

    def _run_side_effect(args: list[str], **kwargs: object) -> MagicMock:
        if args[:3] == ["gh", "pr", "create"]:
            return MagicMock(returncode=0, stdout="https://github.com/org/repo/pull/1\n")
        if args[:2] == ["git", "rev-parse"]:
            return MagicMock(returncode=0, stdout="task/T-001\n")
        return MagicMock(returncode=0)  # git push

    mock_subprocess.run.side_effect = _run_side_effect

    with patch.object(Path, "read_text", autospec=True, wraps=Path.read_text) as mock_read_text:
        lc._create_pr("T-001", pr_body_override="body")

    active_file_call = next(c for c in mock_read_text.call_args_list if c.args[0] == active_file)
    assert active_file_call.kwargs.get("encoding") == "utf-8"


@patch("shutil.which", return_value="/usr/bin/gh")
@patch("ydk.core.task_lifecycle.subprocess")
def test_create_pr_uses_own_base_branch_per_task(
    mock_subprocess: MagicMock,
    mock_which: MagicMock,
    mock_repo: MagicMock,
    mock_worktree: MagicMock,
    mock_verifier: MagicMock,
    tmp_path: Path,
) -> None:
    """Two tasks started with different base branches each get their own
    base_branch back out of active-task.json -- never the other task's.

    Regression test for the bug where active-task.json held a single
    {"task_id", "base_branch"} slot for the whole repo: whichever task
    called start() last clobbered the file for every other task in flight.
    """
    events = EventBus()
    lc = TaskLifecycle(
        repo=mock_repo,
        events=events,
        worktree_mgr=mock_worktree,
        verifier=mock_verifier,
        project_root=tmp_path,
    )
    mock_worktree.get_worktree_path.return_value = None

    lc.start("T-001", base_branch="branch-a")
    lc.start("T-002", base_branch="branch-b")

    def _run_side_effect(args: list[str], **kwargs: object) -> MagicMock:
        if args[:3] == ["gh", "pr", "create"]:
            return MagicMock(returncode=0, stdout="https://github.com/org/repo/pull/1\n")
        if args[:2] == ["git", "rev-parse"]:
            return MagicMock(returncode=0, stdout="task/branch\n")
        return MagicMock(returncode=0)  # git push

    mock_subprocess.run.side_effect = _run_side_effect

    lc._create_pr("T-002", pr_body_override="body")
    lc._create_pr("T-001", pr_body_override="body")

    create_calls = [c for c in mock_subprocess.run.call_args_list if c.args[0][:3] == ["gh", "pr", "create"]]
    assert len(create_calls) == 2

    def _base_arg(call: MagicMock) -> str:
        argv = call.args[0]
        return argv[argv.index("--base") + 1]

    assert _base_arg(create_calls[0]) == "branch-b"
    assert _base_arg(create_calls[1]) == "branch-a"


@patch("shutil.which", return_value="/usr/bin/gh")
@patch("ydk.core.task_lifecycle.subprocess")
def test_create_pr_does_not_inherit_base_branch_from_unrelated_task(
    mock_subprocess: MagicMock,
    mock_which: MagicMock,
    mock_repo: MagicMock,
    mock_worktree: MagicMock,
    mock_verifier: MagicMock,
    tmp_path: Path,
) -> None:
    """A task with no active-task.json entry of its own (e.g. a quickdev
    task, which never calls start()) defaults to "main" instead of
    borrowing whatever unrelated task's start() ran most recently.
    """
    events = EventBus()
    lc = TaskLifecycle(
        repo=mock_repo,
        events=events,
        worktree_mgr=mock_worktree,
        verifier=mock_verifier,
        project_root=tmp_path,
    )
    mock_worktree.get_worktree_path.return_value = None

    lc.start("T-001", base_branch="develop")

    def _run_side_effect(args: list[str], **kwargs: object) -> MagicMock:
        if args[:3] == ["gh", "pr", "create"]:
            return MagicMock(returncode=0, stdout="https://github.com/org/repo/pull/1\n")
        if args[:2] == ["git", "rev-parse"]:
            return MagicMock(returncode=0, stdout="task/branch\n")
        return MagicMock(returncode=0)  # git push

    mock_subprocess.run.side_effect = _run_side_effect

    lc._create_pr("QD-abc", pr_body_override="body")

    create_call = next(c for c in mock_subprocess.run.call_args_list if c.args[0][:3] == ["gh", "pr", "create"])
    argv = create_call.args[0]
    assert argv[argv.index("--base") + 1] == "main"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("origin/main", "main"),
        ("main", "main"),
        ("upstream/develop", "develop"),
    ],
)
def test_normalize_base_branch(raw: str, expected: str) -> None:
    """_normalize_base_branch strips a remote prefix, leaving a bare branch
    name unchanged."""
    assert TaskLifecycle._normalize_base_branch(raw) == expected


@patch("shutil.which", return_value="/usr/bin/gh")
@patch("ydk.core.task_lifecycle.subprocess")
def test_create_pr_strips_remote_prefix_from_base_branch(
    mock_subprocess: MagicMock,
    mock_which: MagicMock,
    mock_repo: MagicMock,
    mock_worktree: MagicMock,
    mock_verifier: MagicMock,
    tmp_path: Path,
) -> None:
    """_create_pr passes a bare branch name to `gh pr create --base`, even
    when active-task.json stores a remote-prefixed ref like "origin/main".

    Regression test: "origin/main" is a valid git ref to branch a worktree
    from, but not a valid GitHub branch name -- passing it unmodified to
    `gh pr create --base` fails with a misleading GraphQL error.
    """
    events = EventBus()
    lc = TaskLifecycle(
        repo=mock_repo,
        events=events,
        worktree_mgr=mock_worktree,
        verifier=mock_verifier,
        project_root=tmp_path,
    )
    mock_worktree.get_worktree_path.return_value = None

    ydk_dir = tmp_path / ".ydk"
    ydk_dir.mkdir(parents=True, exist_ok=True)
    active_file = ydk_dir / "active-task.json"
    active_file.write_text('{"tasks": {"T-001": {"base_branch": "origin/main"}}}', encoding="utf-8")

    def _run_side_effect(args: list[str], **kwargs: object) -> MagicMock:
        if args[:3] == ["gh", "pr", "create"]:
            return MagicMock(returncode=0, stdout="https://github.com/org/repo/pull/1\n")
        if args[:2] == ["git", "rev-parse"]:
            return MagicMock(returncode=0, stdout="task/T-001\n")
        return MagicMock(returncode=0)  # git push

    mock_subprocess.run.side_effect = _run_side_effect

    lc._create_pr("T-001", pr_body_override="body")

    create_call = next(c for c in mock_subprocess.run.call_args_list if c.args[0][:3] == ["gh", "pr", "create"])
    argv = create_call.args[0]
    assert argv[argv.index("--base") + 1] == "main"


@patch("shutil.which", return_value="/usr/bin/gh")
@patch("ydk.core.task_lifecycle.subprocess")
def test_create_pr_raises_when_git_push_fails(
    mock_subprocess: MagicMock, mock_which: MagicMock, lifecycle: TaskLifecycle, mock_worktree: MagicMock
) -> None:
    """_create_pr raises instead of silently proceeding when `git push` fails.

    A genuine push failure must not be swallowed -- proceeding as if the
    branch were up to date remotely would let `gh pr create` run against a
    remote branch that doesn't reflect local work.
    """
    mock_worktree.get_worktree_path.return_value = None

    def _run_side_effect(args: list[str], **kwargs: object) -> MagicMock:
        if args[:3] == ["git", "push", "-u"]:
            return MagicMock(returncode=1, stdout="", stderr="fatal: unable to access remote")
        return MagicMock(returncode=0)

    mock_subprocess.run.side_effect = _run_side_effect

    with pytest.raises(RuntimeError) as exc_info:
        lifecycle._create_pr("T-001", pr_body_override="some body")

    message = str(exc_info.value)
    assert "T-001" in message
    assert "unable to access remote" in message

    gh_calls = [c for c in mock_subprocess.run.call_args_list if c.args[0][:3] == ["gh", "pr", "create"]]
    assert gh_calls == []


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


@patch("shutil.which", return_value=None)
@patch("ydk.core.task_lifecycle.subprocess")
def test_done_skip_plugin_allows_genuinely_failing_plugin(
    mock_subprocess: MagicMock,
    mock_which: MagicMock,
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
    mock_subprocess.run.return_value.returncode = 0

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


@patch("shutil.which", return_value=None)
@patch("ydk.core.task_lifecycle.subprocess")
def test_done_runs_pr_body_validation_after_body_is_built(
    mock_subprocess: MagicMock,
    mock_which: MagicMock,
    lifecycle: TaskLifecycle,
    mock_verifier: MagicMock,
    mock_worktree: MagicMock,
) -> None:
    """done() invokes pr-body-validation by name, after the real PR body exists."""
    report = VerificationReport(
        timestamp="2025-01-01T00:00:00Z",
        checks=[CheckResult(name="lint", passed=True, output="ok", duration_seconds=1.0)],
        all_passed=True,
        total_duration_seconds=1.0,
    )
    mock_verifier.run_all = AsyncMock(return_value=report)
    mock_worktree.get_worktree_path.return_value = None
    mock_subprocess.run.return_value.returncode = 0

    fake_plugin = MagicMock()
    mock_verifier.discover_plugins.return_value = [fake_plugin]
    mock_verifier.filter_by_name.return_value = [fake_plugin]
    mock_verifier.run_layer = AsyncMock(
        return_value=[CheckResult(name="pr-body-validation", passed=True, output="PASS", duration_seconds=0.1)]
    )

    result = lifecycle.done("T-001")

    assert result["passed"] is True
    mock_verifier.filter_by_name.assert_called_once_with([fake_plugin], "pr-body-validation")
    run_layer_args = mock_verifier.run_layer.call_args[0]
    assert run_layer_args[0] == [fake_plugin]
    assert "## Summary" in run_layer_args[1]["pr_body"]


@patch("ydk.core.task_lifecycle.subprocess")
def test_done_blocks_pr_when_pr_body_validation_fails(
    mock_subprocess: MagicMock,
    lifecycle: TaskLifecycle,
    mock_verifier: MagicMock,
    mock_repo: MagicMock,
    mock_worktree: MagicMock,
) -> None:
    """done() blocks PR creation when the pr-body-validation gate fails."""
    report = VerificationReport(
        timestamp="2025-01-01T00:00:00Z",
        checks=[CheckResult(name="lint", passed=True, output="ok", duration_seconds=1.0)],
        all_passed=True,
        total_duration_seconds=1.0,
    )
    mock_verifier.run_all = AsyncMock(return_value=report)
    mock_worktree.get_worktree_path.return_value = None

    fake_plugin = MagicMock()
    mock_verifier.discover_plugins.return_value = [fake_plugin]
    mock_verifier.filter_by_name.return_value = [fake_plugin]
    mock_verifier.run_layer = AsyncMock(
        return_value=[
            CheckResult(
                name="pr-body-validation",
                passed=False,
                output="FAIL: Missing requirements: console_block",
                duration_seconds=0.1,
            )
        ]
    )

    result = lifecycle.done("T-001")

    assert result["passed"] is False
    assert "pr_url" not in result
    mock_subprocess.run.assert_not_called()
    assert mock_repo.add_comment.call_args[0][0] == "T-001"
    assert "pr-body-validation FAILED" in mock_repo.add_comment.call_args[0][1]


def test_done_skip_plugins_bypasses_pr_body_validation_gate(
    lifecycle: TaskLifecycle,
    mock_verifier: MagicMock,
    mock_repo: MagicMock,
    mock_worktree: MagicMock,
) -> None:
    """skip_plugins=['pr-body-validation'] skips the gate instead of blocking the PR."""
    report = VerificationReport(
        timestamp="2025-01-01T00:00:00Z",
        checks=[CheckResult(name="lint", passed=True, output="ok", duration_seconds=1.0)],
        all_passed=True,
        total_duration_seconds=1.0,
    )
    mock_verifier.run_all = AsyncMock(return_value=report)
    mock_worktree.get_worktree_path.return_value = None

    fake_plugin = MagicMock()
    mock_verifier.discover_plugins.return_value = [fake_plugin]
    mock_verifier.filter_by_name.return_value = [fake_plugin]
    mock_verifier.run_layer = AsyncMock(
        return_value=[CheckResult(name="pr-body-validation", passed=False, output="FAIL", duration_seconds=0.1)]
    )

    with patch("ydk.core.task_lifecycle.subprocess") as mock_subprocess, patch("shutil.which", return_value=None):
        mock_subprocess.run.return_value.returncode = 0
        result = lifecycle.done("T-001", skip_plugins=["pr-body-validation"])

    assert result["passed"] is True
    mock_verifier.run_layer.assert_not_called()


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
        '@pytest.mark.xfail(reason="YDK-TODO-0042: implement StrategyService.create")\n'
        "def test_create_strategy():\n"
        "    pass\n"
    )

    # Override project root
    lifecycle._root = tmp_path

    # Mock TodoManager at its source module
    with patch("ydk.core.todo_manager.TodoManager") as mock_todo_cls:
        mock_mgr = MagicMock()
        mock_todo_cls.return_value = mock_mgr
        mock_todo = MagicMock()
        mock_todo.id = "YDK-TODO-0042"
        mock_todo.task_id = "T-001"
        mock_mgr.list_todos.return_value = [mock_todo]

        warnings = lifecycle._check_xfail_removed(
            "T-001",
            ["app/api/routes/strategies.py"],
        )

    assert len(warnings) == 1
    assert "YDK-TODO-0042" in warnings[0]


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

    with patch("ydk.core.todo_manager.TodoManager") as mock_todo_cls:
        mock_mgr = MagicMock()
        mock_todo_cls.return_value = mock_mgr
        mock_todo = MagicMock()
        mock_todo.id = "YDK-TODO-0042"
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


@patch("shutil.which", return_value=None)
@patch("ydk.core.task_lifecycle.subprocess")
def test_done_removes_active_task_file(
    mock_subprocess: MagicMock,
    mock_which: MagicMock,
    mock_repo: MagicMock,
    mock_worktree: MagicMock,
    mock_verifier: MagicMock,
    tmp_path: Path,
) -> None:
    """ydk task done removes .ydk/active-task.json after success."""
    events = EventBus()
    lc = TaskLifecycle(
        repo=mock_repo,
        events=events,
        worktree_mgr=mock_worktree,
        verifier=mock_verifier,
        project_root=tmp_path,
    )

    # Create active-task.json (simulating task start)
    ydk_dir = tmp_path / ".ydk"
    ydk_dir.mkdir(parents=True, exist_ok=True)
    active_file = ydk_dir / "active-task.json"
    active_file.write_text('{"tasks": {"T-001": {"base_branch": "main"}}}')

    report = VerificationReport(
        timestamp="2025-01-01T00:00:00Z",
        checks=[CheckResult(name="lint", passed=True, output="ok", duration_seconds=1.0)],
        all_passed=True,
        total_duration_seconds=1.0,
    )
    mock_verifier.run_all = AsyncMock(return_value=report)
    mock_worktree.get_worktree_path.return_value = None
    mock_subprocess.run.return_value.returncode = 0

    result = lc.done("T-001")

    assert result["passed"] is True
    assert not active_file.exists(), "active-task.json should be removed after successful done"


@patch("shutil.which", return_value=None)
@patch("ydk.core.task_lifecycle.subprocess")
def test_done_removes_only_own_entry_when_other_tasks_still_active(
    mock_subprocess: MagicMock,
    mock_which: MagicMock,
    mock_repo: MagicMock,
    mock_worktree: MagicMock,
    mock_verifier: MagicMock,
    tmp_path: Path,
) -> None:
    """done() removes only its own task's entry, leaving other in-flight
    tasks' active-task.json entries (and their base branches) intact.
    """
    events = EventBus()
    lc = TaskLifecycle(
        repo=mock_repo,
        events=events,
        worktree_mgr=mock_worktree,
        verifier=mock_verifier,
        project_root=tmp_path,
    )

    ydk_dir = tmp_path / ".ydk"
    ydk_dir.mkdir(parents=True, exist_ok=True)
    active_file = ydk_dir / "active-task.json"
    active_file.write_text(
        '{"tasks": {"T-001": {"base_branch": "main"}, "T-002": {"base_branch": "develop"}}}',
        encoding="utf-8",
    )

    report = VerificationReport(
        timestamp="2025-01-01T00:00:00Z",
        checks=[CheckResult(name="lint", passed=True, output="ok", duration_seconds=1.0)],
        all_passed=True,
        total_duration_seconds=1.0,
    )
    mock_verifier.run_all = AsyncMock(return_value=report)
    mock_worktree.get_worktree_path.return_value = None
    mock_subprocess.run.return_value.returncode = 0

    result = lc.done("T-001")

    assert result["passed"] is True
    assert active_file.exists(), "active-task.json should survive while T-002 is still in flight"
    remaining = json.loads(active_file.read_text(encoding="utf-8"))
    assert "T-001" not in remaining["tasks"]
    assert remaining["tasks"]["T-002"]["base_branch"] == "develop"


def test_done_scopes_verification_to_worktree_not_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test for #37: content-scanning plugins must scan the task's
    worktree, not wherever the process cwd happened to be when the lifecycle
    was constructed.

    Simulates ``ydk task done`` invoked from the main checkout (cwd) while the
    task's actual files live in a separate worktree. Runs the real
    ``python-file-length`` plugin (a real content-scanning verification
    plugin, not a mock) and asserts it scans the worktree — not the cwd-bound
    project_root — by placing an over-limit file only inside the worktree.
    """
    main_root = tmp_path / "main"
    worktree_root = tmp_path / "worktree"
    main_root.mkdir()
    (worktree_root / "app").mkdir(parents=True)

    # Oversized file only exists in the worktree. If verification scans
    # main_root (the old cwd-bound project_root) it silently misses this
    # violation, since main_root has no app/ directory at all.
    big_file = worktree_root / "app" / "big.py"
    big_file.write_text("\n".join(f"x{i} = {i}" for i in range(400)))

    # Process cwd is main_root, simulating `ydk task done` invoked from the
    # main checkout rather than from inside the task's worktree.
    monkeypatch.chdir(main_root)

    mock_repo = MagicMock()
    mock_repo.get_task.return_value = TaskDetail(id="T-037", title="Test task", story_id="S-001")

    mock_worktree = MagicMock()
    mock_worktree.get_worktree_path.return_value = worktree_root

    verifier = Verifier(project_root=main_root, enabled_plugins=["python-file-length"], use_cache=False)

    lc = TaskLifecycle(
        repo=mock_repo,
        events=EventBus(),
        worktree_mgr=mock_worktree,
        verifier=verifier,
        project_root=main_root,
    )

    result = lc.done("T-037")

    assert result["passed"] is False, "verification should have caught the over-limit file in the worktree"
    check = result["report"].checks[0]
    assert check.name == "python-file-length"
    assert "big.py" in check.output

"""Tests for odk.core.git_worktree — WorktreeManager with real git repos."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from odk.core.git_worktree import WorktreeManager

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one commit."""
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True)
    # Create initial commit
    (tmp_path / "README.md").write_text("# test")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    return tmp_path


def test_create_makes_worktree_directory_and_branch(git_repo: Path) -> None:
    """create() produces a worktree directory and a git branch."""
    mgr = WorktreeManager(git_repo)
    path = mgr.create("T-001")

    assert path.exists()
    assert path == git_repo / ".odk" / "worktrees" / "T-001"

    # Branch should exist
    result = subprocess.run(
        ["git", "branch", "--list", "task/T-001"],
        cwd=str(git_repo),
        capture_output=True,
        text=True,
    )
    assert "task/T-001" in result.stdout


def test_create_with_description_slugifies_branch(git_repo: Path) -> None:
    """create() with description produces a slugified branch name."""
    mgr = WorktreeManager(git_repo)
    path = mgr.create("T-002", description="Add user login")

    assert path.exists()

    result = subprocess.run(
        ["git", "branch", "--list", "task/T-002*"],
        cwd=str(git_repo),
        capture_output=True,
        text=True,
    )
    assert "task/T-002-add-user-login" in result.stdout


def test_cleanup_removes_worktree_and_branch(git_repo: Path) -> None:
    """cleanup() removes the worktree directory and deletes the branch."""
    mgr = WorktreeManager(git_repo)
    mgr.create("T-003")

    assert (git_repo / ".odk" / "worktrees" / "T-003").exists()

    mgr.cleanup("T-003")

    assert not (git_repo / ".odk" / "worktrees" / "T-003").exists()

    result = subprocess.run(
        ["git", "branch", "--list", "task/T-003*"],
        cwd=str(git_repo),
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ""


def test_get_worktree_path_returns_none_when_missing(git_repo: Path) -> None:
    """get_worktree_path() returns None for a nonexistent worktree."""
    mgr = WorktreeManager(git_repo)
    assert mgr.get_worktree_path("T-999") is None


def test_get_worktree_path_returns_path_when_exists(git_repo: Path) -> None:
    """get_worktree_path() returns the Path when the worktree exists."""
    mgr = WorktreeManager(git_repo)
    mgr.create("T-004")
    path = mgr.get_worktree_path("T-004")
    assert path is not None
    assert path.exists()


def test_list_worktrees_returns_active_task_ids(git_repo: Path) -> None:
    """list_worktrees() returns IDs of all active worktrees."""
    mgr = WorktreeManager(git_repo)
    assert mgr.list_worktrees() == []

    mgr.create("T-010")
    mgr.create("T-011")

    ids = sorted(mgr.list_worktrees())
    assert ids == ["T-010", "T-011"]


def test_list_worktrees_empty_when_no_dir(tmp_path: Path) -> None:
    """list_worktrees() returns empty list when .odk/worktrees doesn't exist."""
    mgr = WorktreeManager(tmp_path)
    assert mgr.list_worktrees() == []


def test_create_with_base_branch(git_repo: Path) -> None:
    """create() with base_branch creates the worktree branch from the specified base."""
    # Create a feature branch with a unique commit
    subprocess.run(["git", "checkout", "-b", "feature/foo"], cwd=str(git_repo), capture_output=True, check=True)
    (git_repo / "feature.txt").write_text("feature content")
    subprocess.run(["git", "add", "."], cwd=str(git_repo), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "feature commit"], cwd=str(git_repo), capture_output=True, check=True)
    # Go back to main
    subprocess.run(["git", "checkout", "main"], cwd=str(git_repo), capture_output=True)
    # Fallback: might be 'master'
    subprocess.run(["git", "checkout", "master"], cwd=str(git_repo), capture_output=True)

    mgr = WorktreeManager(git_repo)
    path = mgr.create("T-020", base_branch="feature/foo")

    assert path.exists()
    # The worktree should contain the feature file (branched from feature/foo)
    assert (path / "feature.txt").exists()


def test_create_defaults_to_head_not_main(git_repo: Path) -> None:
    """create() without base_branch uses HEAD, not hardcoded main."""
    # Create a feature branch with a unique commit and stay on it
    subprocess.run(["git", "checkout", "-b", "feature/bar"], cwd=str(git_repo), capture_output=True, check=True)
    (git_repo / "bar.txt").write_text("bar content")
    subprocess.run(["git", "add", "."], cwd=str(git_repo), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "bar commit"], cwd=str(git_repo), capture_output=True, check=True)

    # HEAD is now feature/bar
    mgr = WorktreeManager(git_repo)
    path = mgr.create("T-021")

    assert path.exists()
    # The worktree should contain bar.txt since HEAD was feature/bar
    assert (path / "bar.txt").exists()

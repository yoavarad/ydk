"""Tests for ydk.core.active_task -- resolving active-task.json to the main checkout."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ydk.core.active_task import resolve_active_task_file


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def main_and_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """A real git repo (main checkout) plus a real linked worktree."""
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q")
    _git(main, "config", "user.email", "test@example.com")
    _git(main, "config", "user.name", "Test")
    (main / "README.md").write_text("hello\n")
    _git(main, "add", ".")
    _git(main, "commit", "-q", "-m", "feat: initial")
    worktree = main / ".ydk" / "worktrees" / "1"
    _git(main, "worktree", "add", "-q", "-b", "task/1", str(worktree))
    return main, worktree


def test_resolves_to_project_root_outside_git(tmp_path: Path) -> None:
    assert resolve_active_task_file(tmp_path) == tmp_path / ".ydk" / "active-task.json"


def test_resolves_to_project_root_in_main_checkout(main_and_worktree: tuple[Path, Path]) -> None:
    main, _ = main_and_worktree
    assert resolve_active_task_file(main) == main / ".ydk" / "active-task.json"


def test_resolves_to_main_checkout_from_linked_worktree(main_and_worktree: tuple[Path, Path]) -> None:
    main, worktree = main_and_worktree
    resolved = resolve_active_task_file(worktree)
    assert resolved.resolve() == (main / ".ydk" / "active-task.json").resolve()


def test_ignores_inherited_git_dir_env_from_linked_worktree(
    main_and_worktree: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A GIT_DIR set by a git hook/wrapper must not mask the linked worktree."""
    main, worktree = main_and_worktree
    monkeypatch.setenv("GIT_DIR", str(main / ".git"))
    resolved = resolve_active_task_file(worktree)
    assert resolved.resolve() == (main / ".ydk" / "active-task.json").resolve()


def test_falls_back_when_common_dir_is_not_dot_git(tmp_path: Path) -> None:
    """Worktree of a bare repo: no main checkout to point at, keep project root."""
    bare = tmp_path / "repo.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-q")
    _git(seed, "config", "user.email", "test@example.com")
    _git(seed, "config", "user.name", "Test")
    (seed / "README.md").write_text("hello\n")
    _git(seed, "add", ".")
    _git(seed, "commit", "-q", "-m", "feat: initial")
    _git(tmp_path, "clone", "-q", "--bare", str(seed), str(bare))
    worktree = tmp_path / "wt"
    _git(bare, "worktree", "add", "-q", "-b", "task/1", str(worktree))
    assert resolve_active_task_file(worktree) == worktree / ".ydk" / "active-task.json"


def test_resolves_relative_root_from_linked_worktree(
    main_and_worktree: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ydk task done`` uses ``Path(".")`` as project root, run from the worktree."""
    main, worktree = main_and_worktree
    monkeypatch.chdir(worktree)
    resolved = resolve_active_task_file(Path("."))
    assert resolved.resolve() == (main / ".ydk" / "active-task.json").resolve()

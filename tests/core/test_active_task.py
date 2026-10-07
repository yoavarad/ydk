"""Tests for ydk.core.active_task -- resolving active-task.json to the main checkout."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ydk.core.active_task import prune_active_tasks, resolve_active_task_file


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


def _write_entries(root: Path, ids: list[str]) -> Path:
    f = root / ".ydk" / "active-task.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"tasks": {i: {"base_branch": "main"} for i in ids}}), encoding="utf-8")
    return f


class TestPruneActiveTasks:
    def test_removes_only_named_ids(self, tmp_path: Path) -> None:
        f = _write_entries(tmp_path, ["1", "2", "3"])
        prune_active_tasks(tmp_path, {"1", "3"})
        assert list(json.loads(f.read_text(encoding="utf-8"))["tasks"]) == ["2"]

    def test_deletes_file_when_empty(self, tmp_path: Path) -> None:
        f = _write_entries(tmp_path, ["1"])
        prune_active_tasks(tmp_path, {"1"})
        assert not f.exists()

    def test_missing_file_is_noop(self, tmp_path: Path) -> None:
        prune_active_tasks(tmp_path, {"1"})
        assert not (tmp_path / ".ydk" / "active-task.json").exists()

    def test_unmatched_ids_leave_file_untouched(self, tmp_path: Path) -> None:
        f = _write_entries(tmp_path, ["2"])
        before = f.read_text(encoding="utf-8")
        prune_active_tasks(tmp_path, {"9"})
        assert f.read_text(encoding="utf-8") == before

    def test_targets_main_checkout_from_worktree(
        self, main_and_worktree: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        main, worktree = main_and_worktree
        f = _write_entries(main, ["1", "2"])
        monkeypatch.chdir(worktree)
        prune_active_tasks(Path("."), {"1"})
        assert list(json.loads(f.read_text(encoding="utf-8"))["tasks"]) == ["2"]

    @pytest.mark.parametrize("content", ["not json", "null", "[]", '{"tasks": []}'])
    def test_malformed_file_is_left_alone(self, tmp_path: Path, content: str) -> None:
        f = tmp_path / ".ydk" / "active-task.json"
        f.parent.mkdir(parents=True)
        f.write_text(content, encoding="utf-8")
        prune_active_tasks(tmp_path, {"1"})
        assert f.read_text(encoding="utf-8") == content

    def test_legacy_single_slot_format(self, tmp_path: Path) -> None:
        f = tmp_path / ".ydk" / "active-task.json"
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps({"task_id": "1", "base_branch": "main"}), encoding="utf-8")
        prune_active_tasks(tmp_path, {"1"})
        assert not f.exists()

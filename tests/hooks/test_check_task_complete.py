"""Tests for the SubagentStop hook src/ydk/hooks/check_task_complete.sh."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / "src" / "ydk" / "hooks" / "check_task_complete.sh"


def _bash_has_python3() -> bool:
    """The hook shells out to python3; skip where bash can't run a real one
    (e.g. Windows Store python3 stub)."""
    if shutil.which("bash") is None:
        return False
    probe = subprocess.run(["bash", "-c", "python3 -c 'import json'"], capture_output=True)
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(not _bash_has_python3(), reason="needs bash with a working python3")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def main_and_worktree(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q")
    _git(main, "config", "user.email", "test@example.com")
    _git(main, "config", "user.name", "Test")
    (main / "README.md").write_text("hello\n")
    _git(main, "add", ".")
    _git(main, "commit", "-q", "-m", "feat: initial")
    worktree = main / ".ydk" / "worktrees" / "7"
    _git(main, "worktree", "add", "-q", "-b", "task/7", str(worktree))
    return main, worktree


def _run_hook(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", HOOK.as_posix()], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def _write_active(root: Path, tasks: dict) -> None:
    (root / ".ydk").mkdir(exist_ok=True)
    (root / ".ydk" / "active-task.json").write_text(json.dumps({"tasks": tasks}), encoding="utf-8")


def test_hook_from_worktree_reads_main_checkout_file(main_and_worktree: tuple[Path, Path]) -> None:
    main, worktree = main_and_worktree
    _write_active(main, {"7": {"base_branch": "main"}})

    result = _run_hook(worktree)

    assert result.returncode == 2
    assert "7" in result.stdout


def test_hook_from_worktree_allows_when_main_has_no_file(main_and_worktree: tuple[Path, Path]) -> None:
    _, worktree = main_and_worktree
    assert _run_hook(worktree).returncode == 0


def test_hook_from_main_checkout_unchanged(main_and_worktree: tuple[Path, Path]) -> None:
    main, _ = main_and_worktree
    assert _run_hook(main).returncode == 0
    _write_active(main, {"9": {"base_branch": "main"}})
    result = _run_hook(main)
    assert result.returncode == 2
    assert "9" in result.stdout


def test_hook_outside_git_reads_cwd_file(tmp_path: Path) -> None:
    _write_active(tmp_path, {"5": {"base_branch": "main"}})
    assert _run_hook(tmp_path).returncode == 2

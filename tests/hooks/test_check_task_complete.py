"""Tests for the SubagentStop hook src/ydk/hooks/check_task_complete.sh."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / "src" / "ydk" / "hooks" / "check_task_complete.sh"

HookRunner = Callable[[Path], "subprocess.CompletedProcess[str]"]


def _resolve_bash() -> str | None:
    """Pick a bash that can execute the hook. On Windows prefer Git Bash (found by
    walking up from git's location) over the WindowsApps WSL launcher, which can't
    read C:/ paths."""
    if sys.platform == "win32":
        git = shutil.which("git")
        if git is not None:
            for ancestor in Path(git).resolve().parents:
                for rel in ("bin/bash.exe", "usr/bin/bash.exe"):
                    candidate = ancestor / rel
                    if candidate.is_file():
                        return str(candidate)
    return shutil.which("bash")


def _hook_env(shim_dir: Path) -> dict[str, str]:
    """On Windows the python3 on bash's PATH is usually the Store stub; point a
    python3 shim at the interpreter running the tests so the hook can run."""
    env = os.environ.copy()
    if sys.platform == "win32":
        shim = shim_dir / "python3"
        shim.write_text(
            f'#!/bin/sh\nexec {shlex.quote(Path(sys.executable).as_posix())} "$@"\n', encoding="utf-8", newline="\n"
        )
        env["PATH"] = f"{shim_dir.as_posix()}{os.pathsep}{env.get('PATH', '')}"
    return env


def _bash_can_run_hook(bash: str | None, env: dict[str, str] | None = None) -> bool:
    """The hook shells out to python3 and must be readable at HOOK.as_posix();
    skip where bash can't do both (e.g. WSL bash, Windows Store python3 stub)."""
    if bash is None:
        return False
    probe = subprocess.run(
        [bash, "-c", 'test -r "$1" && python3 -c "import json"', "_", HOOK.as_posix()],
        capture_output=True,
        env=env,
    )
    return probe.returncode == 0


@pytest.fixture(scope="session")
def run_hook(tmp_path_factory: pytest.TempPathFactory) -> HookRunner:
    bash = _resolve_bash()
    env = _hook_env(tmp_path_factory.mktemp("py3-shim"))
    if bash is None or not _bash_can_run_hook(bash, env):
        pytest.skip("needs bash that can read the hook path and run python3")

    def _run(cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [bash, HOOK.as_posix()],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    return _run


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


def _write_active(root: Path, tasks: dict) -> None:
    (root / ".ydk").mkdir(exist_ok=True)
    (root / ".ydk" / "active-task.json").write_text(json.dumps({"tasks": tasks}), encoding="utf-8")


def test_hook_from_worktree_reads_main_checkout_file(
    main_and_worktree: tuple[Path, Path], run_hook: HookRunner
) -> None:
    main, worktree = main_and_worktree
    _write_active(main, {"7": {"base_branch": "main"}})

    result = run_hook(worktree)

    assert result.returncode == 2
    assert "7" in result.stdout


def test_hook_from_worktree_allows_when_main_has_no_file(
    main_and_worktree: tuple[Path, Path], run_hook: HookRunner
) -> None:
    _, worktree = main_and_worktree
    assert run_hook(worktree).returncode == 0


def test_hook_from_main_checkout_unchanged(main_and_worktree: tuple[Path, Path], run_hook: HookRunner) -> None:
    main, _ = main_and_worktree
    assert run_hook(main).returncode == 0
    _write_active(main, {"9": {"base_branch": "main"}})
    result = run_hook(main)
    assert result.returncode == 2
    assert "9" in result.stdout


def test_hook_outside_git_reads_cwd_file(tmp_path: Path, run_hook: HookRunner) -> None:
    _write_active(tmp_path, {"5": {"base_branch": "main"}})
    assert run_hook(tmp_path).returncode == 2


def test_resolve_bash_prefers_git_bash_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    git_bash = tmp_path / "Git" / "bin" / "bash.exe"
    git_bash.parent.mkdir(parents=True)
    git_bash.write_text("")
    (tmp_path / "Git" / "cmd").mkdir()
    git_exe = tmp_path / "Git" / "cmd" / "git.exe"
    git_exe.write_text("")
    which = {"git": str(git_exe), "bash": "wsl-bash"}
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which", lambda name: which.get(name))

    assert _resolve_bash() == str(git_bash.resolve())


def test_resolve_bash_finds_git_bash_above_mingw64(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    git_bash = tmp_path / "Git" / "usr" / "bin" / "bash.exe"
    git_bash.parent.mkdir(parents=True)
    git_bash.write_text("")
    git_exe = tmp_path / "Git" / "mingw64" / "bin" / "git.exe"
    git_exe.parent.mkdir(parents=True)
    git_exe.write_text("")
    which = {"git": str(git_exe), "bash": "wsl-bash"}
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which", lambda name: which.get(name))

    assert _resolve_bash() == str(git_bash.resolve())


def test_resolve_bash_uses_path_bash_elsewhere(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/bash" if name == "bash" else None)

    assert _resolve_bash() == "/usr/bin/bash"


def test_bash_can_run_hook_false_when_no_bash() -> None:
    assert _bash_can_run_hook(None) is False

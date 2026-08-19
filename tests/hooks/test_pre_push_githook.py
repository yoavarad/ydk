"""Tests for the repo's own dev pre-push hook (.githooks/pre-push).

Covers graceful degradation (skip, not crash) when ``uv`` isn't on PATH or
the repo being pushed has no Python project markers (GitHub issue #3).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PRE_PUSH_SCRIPT = Path(__file__).resolve().parents[2] / ".githooks" / "pre-push"

# PATH that has git (required by the hook itself for branch checks) but
# deliberately excludes uv — simulates a machine without uv installed.
_GIT_ONLY_PATH = os.path.dirname(shutil.which("git") or "")


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo on a conventionally-named branch."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "feat: initial"], cwd=tmp_path, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "feat/test-branch"], cwd=tmp_path, check=True)
    return tmp_path


def _run_pre_push(cwd: Path, path_env: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if path_env is not None:
        env["PATH"] = path_env
    return subprocess.run(
        [sys.executable, str(PRE_PUSH_SCRIPT)],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


def test_skips_unit_tests_when_uv_missing(git_repo: Path) -> None:
    """Hook does not crash when uv isn't on PATH — it skips the unit-tests step."""
    result = _run_pre_push(git_repo, path_env=_GIT_ONLY_PATH)
    assert result.returncode == 0
    assert "SKIP" in result.stdout
    assert "uv not found" in result.stdout


def test_skips_unit_tests_when_no_python_project(git_repo: Path) -> None:
    """Hook does not crash for a non-Python project (no pyproject.toml/tests/), even with uv on PATH."""
    # Put a fake `uv` on PATH (alongside git) so we specifically exercise the "no project" branch.
    fake_bin = git_repo / "fake_bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / ("uv.bat" if os.name == "nt" else "uv")
    fake_uv.write_text("echo fake uv\n")
    fake_uv.chmod(0o755)

    path_env = os.pathsep.join([str(fake_bin), _GIT_ONLY_PATH])
    result = _run_pre_push(git_repo, path_env=path_env)
    assert result.returncode == 0
    assert "SKIP" in result.stdout
    assert "no Python project" in result.stdout

"""Concrete git implementation using subprocess."""

from __future__ import annotations

import functools
import subprocess
from pathlib import Path


def _run_text(cmd: list[str], cwd: str | Path | None, timeout: int) -> str:
    """Stdout of *cmd* stripped; empty string on any failure."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def default_branch(repo_root: str | Path | None = None) -> str:
    """Resolve the repo default branch: origin/HEAD, then ``gh``, then ``main``.

    Cached per resolved repo root for the life of the process so the ``gh``
    network fallback runs at most once per repo.
    """
    return _default_branch_cached(str(Path(repo_root or ".").resolve()))


@functools.cache
def _default_branch_cached(repo_root: str) -> str:
    out = _run_text(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], repo_root, 10)
    if out:
        return out.removeprefix("origin/")
    out = _run_text(["gh", "repo", "view", "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name"], repo_root, 20)
    return out or "main"


def merge_base(base: str, cwd: str | Path | None = None) -> str | None:
    """Merge-base SHA of *base* and HEAD, preferring ``origin/<base>`` over local ``<base>``.

    ``None`` when neither ref resolves (callers fall back to the whole project).
    """
    base = base.removeprefix("origin/")
    for ref in (f"origin/{base}", base):
        sha = _run_text(["git", "merge-base", ref, "HEAD"], cwd, 10)
        if sha:
            return sha
    return None


class LocalGitService:
    """Git operations via subprocess."""

    def __init__(self, cwd: str | None = None) -> None:
        self._cwd = cwd

    def changed_files(self, directory: str, base_ref: str | None = None, extension: str = ".md") -> list[str]:
        """Return files changed vs base_ref, filtered by extension.

        Falls back to git ls-files if diff fails (e.g. base ref doesn't exist).
        """
        base_ref = base_ref or default_branch(self._cwd)
        result = subprocess.run(
            ["git", "diff", base_ref, "--name-only", "--", directory],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=self._cwd,
        )
        if result.returncode != 0:
            # Fallback: list tracked files in directory
            result = subprocess.run(
                ["git", "ls-files", "--", directory],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=self._cwd,
            )

        lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
        return [f for f in lines if f.endswith(extension)]

    def all_files(self, directory: str, extension: str = ".md") -> list[str]:
        """Find all files with the given extension under directory."""
        dir_path = Path(directory)
        if not dir_path.is_dir():
            return []
        return sorted(str(p) for p in dir_path.glob(f"**/*{extension}"))

    def read_content(self, files: list[str]) -> str:
        """Concatenate files into a single string, each prefixed with path."""
        if not files:
            return ""
        sections: list[str] = []
        for filepath in files:
            path = Path(filepath)
            if not path.is_file():
                continue
            content = path.read_text(encoding="utf-8")
            sections.append(f"# File: {filepath}\n\n{content}")
        return "\n\n---\n\n".join(sections)

    def current_branch(self) -> str:
        """Return the current git branch name."""
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=self._cwd,
        )
        if result.returncode != 0:
            msg = f"Failed to get current branch: {result.stderr.strip()}"
            raise RuntimeError(msg)
        return result.stdout.strip()

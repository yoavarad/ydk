"""Concrete git implementation using subprocess."""

from __future__ import annotations

import functools
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


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


def _ref_exists(root: Path, ref: str) -> bool:
    return bool(_run_text(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], root, 10))


def resolve_start_point(repo_root: str | Path, base_branch: str | None = None) -> str:
    """Ref a new task branch should fork from, matching the PR base.

    ``base = base_branch or default_branch``; best-effort ``git fetch origin <base>``
    (failure logs a warning). Returns ``origin/<base>`` if it exists, else local
    ``<base>``; raises ``ValueError`` when neither resolves.
    """
    root = Path(repo_root)
    base = (base_branch or default_branch(root)).removeprefix("origin/")
    if _run_text(["git", "remote", "get-url", "origin"], root, 10):
        try:
            fetched = (
                subprocess.run(
                    ["git", "fetch", "origin", base], cwd=str(root), capture_output=True, timeout=60
                ).returncode
                == 0
            )
        except (OSError, subprocess.TimeoutExpired):
            fetched = False
        if not fetched:
            logger.warning("git fetch origin %s failed; using existing refs", base)
    for ref in (f"origin/{base}", base):
        if _ref_exists(root, ref):
            return ref
    msg = f"Base branch '{base}' not found locally or on origin"
    raise ValueError(msg)


def resolve_start_sha(repo_root: str | Path, base_branch: str | None = None) -> str:
    """Like :func:`resolve_start_point` but pinned to the commit SHA it resolves to."""
    root = Path(repo_root)
    ref = resolve_start_point(root, base_branch)
    sha = _run_text(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], root, 10)
    if not sha:
        msg = f"Could not resolve '{ref}' to a commit"
        raise ValueError(msg)
    return sha


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


def _non_ydk(paths: list[str]) -> list[str]:
    return [p for p in paths if not (p == ".ydk" or p.startswith(".ydk/"))]


def uncommitted_paths(cwd: str | Path | None = None) -> list[str] | None:
    """Modified/untracked paths in *cwd*'s work tree, excluding ``.ydk/`` bookkeeping.

    ``None`` when git status cannot run (not a repo), so callers can skip the check.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "-z", "-uall"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    entries = result.stdout.split("\0")
    paths: list[str] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if entry[0] in "RC":  # rename/copy entries are followed by the origin path
            i += 1
    return _non_ydk(paths)


def committed_changes(base: str, cwd: str | Path | None = None) -> list[str] | None:
    """Shippable paths (non-``.ydk/``, plus ``.ydk/retros/``) changed on HEAD since the merge-base with *base*.

    ``None`` when the diff cannot be computed.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    # Retros are shippable content; other .ydk/ paths are bookkeeping.
    return [p for p in paths if p.startswith(".ydk/retros/") or p in _non_ydk([p])]


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

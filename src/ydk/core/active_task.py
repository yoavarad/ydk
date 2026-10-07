"""Locate ``.ydk/active-task.json`` -- always in the main working tree.

``ydk task start`` runs from the main checkout but ``ydk task done`` runs from
the task's linked worktree (``.ydk/worktrees/<id>``). Both must read and write
the same file, so it lives in the main checkout, found via
``git rev-parse --git-common-dir`` (issue #325).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ACTIVE_TASK_RELPATH = Path(".ydk") / "active-task.json"
_GIT_LOCATION_VARS = frozenset({"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"})
_GIT_TIMEOUT_SECONDS = 10


def resolve_active_task_file(project_root: Path) -> Path:
    """Return the main working tree's ``.ydk/active-task.json``.

    From a linked worktree, that is the parent of the shared (common) ``.git``
    dir. From the main checkout, or outside git, it is *project_root*'s own
    file -- unchanged from before. A common dir not named ``.git`` (bare repo,
    submodule) has no main checkout to point at, so it also falls back.
    """
    fallback = project_root / ACTIVE_TASK_RELPATH
    # Inherited GIT_DIR & co. (set by git hooks/wrappers) would make git ignore
    # the cwd and report the main repo even from a linked worktree.
    env = {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_VARS}
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir", "--git-common-dir"],
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return fallback
    lines = result.stdout.splitlines() if result.returncode == 0 else []
    if len(lines) != 2:
        return fallback
    git_dir, common_dir = ((project_root / line.strip()).resolve() for line in lines)
    if git_dir == common_dir or common_dir.name != ".git":
        return fallback
    return common_dir.parent / ACTIVE_TASK_RELPATH

"""Locate ``.ydk/active-task.json`` -- always in the main working tree.

``ydk task start`` runs from the main checkout but ``ydk task done`` runs from
the task's linked worktree (``.ydk/worktrees/<id>``). Both must read and write
the same file, so it lives in the main checkout, found via
``git rev-parse --git-common-dir`` (issue #325).
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

ACTIVE_TASK_RELPATH = Path(".ydk") / "active-task.json"
_GIT_LOCATION_VARS = frozenset({"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"})
_GIT_TIMEOUT_SECONDS = 10
LOCK_TIMEOUT_SECONDS = 10.0
_LOCK_POLL_SECONDS = 0.01
_REPLACE_RETRIES = 50  # Windows: a reader holding the file blocks os.replace/unlink briefly

ActiveTasks = dict[str, dict[str, str]]


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


def _read_tasks(active_task_file: Path) -> ActiveTasks:
    """Per-task map from *active_task_file*; ``{}`` when missing or malformed.

    Migrates the legacy single-slot ``{"task_id": ..., "base_branch": ...}``.
    """
    try:
        data = json.loads(active_task_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    if isinstance(data.get("tasks"), dict):
        return dict(data["tasks"])
    if "task_id" in data:
        return {data["task_id"]: {"base_branch": data.get("base_branch", "main")}}
    return {}


@contextlib.contextmanager
def _exclusive_lock(lock_file: Path, timeout: float) -> Iterator[None]:
    """Hold *lock_file* (created with O_EXCL) for the duration of the block.

    A lock older than *timeout* is a leftover from a crashed process and is
    broken. Gives up with ``TimeoutError`` after ``2 * timeout``.
    """
    deadline = time.monotonic() + 2 * timeout
    while True:
        try:
            os.close(os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except (FileExistsError, PermissionError):  # Windows: lock pending delete -> PermissionError
            if time.monotonic() > deadline:
                raise TimeoutError(f"could not acquire {lock_file} within {2 * timeout:.1f}s") from None
            try:
                stale = time.time() - lock_file.stat().st_mtime > timeout
            except OSError:
                continue  # released between open and stat: retry now
            if stale:
                with contextlib.suppress(OSError):
                    lock_file.unlink()
                continue
            time.sleep(_LOCK_POLL_SECONDS)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            lock_file.unlink()


def _retry_on_permission_error(op: Callable[[], None]) -> None:
    """Run *op*, retrying briefly while Windows reports the file as in use."""
    for _ in range(_REPLACE_RETRIES - 1):
        try:
            op()
            return
        except PermissionError:
            time.sleep(_LOCK_POLL_SECONDS)
    op()


def _write_atomically(active_task_file: Path, tasks: ActiveTasks) -> None:
    fd, tmp = tempfile.mkstemp(dir=active_task_file.parent, prefix=".active-task.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"tasks": tasks}, f)
        _retry_on_permission_error(lambda: os.replace(tmp, active_task_file))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def update_active_tasks(
    project_root: Path,
    mutate: Callable[[ActiveTasks], ActiveTasks],
    *,
    timeout: float = LOCK_TIMEOUT_SECONDS,
) -> None:
    """Apply *mutate* to the main checkout's active-task.json under a lock.

    The single writer path for active-task.json: parallel ``start``/``done``/
    ``close``/``sync`` runs serialize on a sibling ``.lock`` file, and the new
    map is written to a temp file and ``os.replace``d in, so readers never see
    a half-written file. An empty result deletes the file; an unchanged
    result writes nothing. A missing or malformed file reads as ``{}``.
    """
    active_task_file = resolve_active_task_file(project_root)
    active_task_file.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(active_task_file.with_name(active_task_file.name + ".lock"), timeout):
        tasks = _read_tasks(active_task_file)
        updated = mutate(dict(tasks))
        if updated == tasks:
            return
        if updated:
            _write_atomically(active_task_file, updated)
        elif active_task_file.exists():
            _retry_on_permission_error(active_task_file.unlink)


def prune_active_tasks(project_root: Path, task_ids: set[str]) -> None:
    """Remove *task_ids* from the main checkout's active-task.json.

    Other entries are untouched; the file is deleted once no entries remain
    (matching ``ydk task done``). No-op when nothing matches or the file is
    missing, unreadable, malformed or unwritable (best-effort).
    """
    if not task_ids:
        return
    try:
        update_active_tasks(project_root, lambda tasks: {k: v for k, v in tasks.items() if k not in task_ids})
    except OSError:
        return  # best-effort: never fail close/sync over stale-entry cleanup

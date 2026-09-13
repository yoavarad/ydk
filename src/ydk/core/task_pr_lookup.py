"""Task <-> PR lookup helpers, shared by `ydk task close`/`sync` and `ydk doctor`.

Split into `list_prs` (one `gh pr list` call) and `find_task_pr` (matching)
so bulk callers checking many tasks can fetch the PR list once and match it
against each task, instead of shelling out to `gh` once per task.
"""

from __future__ import annotations

import json
import subprocess
from typing import cast

_PR_LIST_LIMIT = 500


def list_prs(limit: int = _PR_LIST_LIMIT) -> list[dict[str, object]]:
    """Fetch all PRs (open+closed+merged) via one `gh pr list` call.

    Returns [] if gh is unavailable, the call fails, or output is malformed.
    """
    cmd = [
        "gh",
        "pr",
        "list",
        "--json",
        "number,url,state,headRefName,mergedAt,createdAt",
        "--state",
        "all",
        "--limit",
        str(limit),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError:
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []

    try:
        prs = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    return cast("list[dict[str, object]]", prs)


def _branch_matches_task(branch: str, task_id: str) -> bool:
    """True if branch's last "/"-separated segment matches task_id (exact) or
    task_id-* (slugged), case-insensitively, independent of the branch's
    leading type segment (e.g. task/, quickdev/, chore/qd-).
    """
    task_id_lower = task_id.lower()
    prefix = f"{task_id_lower}-"
    segment = branch.rsplit("/", 1)[-1].lower()
    return segment == task_id_lower or segment.startswith(prefix)


def find_task_pr(task_id: str, prs: list[dict[str, object]] | None = None) -> dict[str, object] | None:
    """Find the PR associated with a task.

    If *prs* is omitted, calls `list_prs()` itself (single-task convenience
    path). Pass a pre-fetched *prs* list (from `list_prs()`) when checking
    many tasks in a loop, to avoid re-fetching the full PR list per task.
    Returns the most-recently-created matching PR dict, or None.
    """
    if prs is None:
        prs = list_prs()

    matches = [pr for pr in prs if _branch_matches_task(str(pr.get("headRefName", "")), task_id)]
    if not matches:
        return None

    matches.sort(key=lambda pr: pr.get("createdAt") or "", reverse=True)
    return matches[0]

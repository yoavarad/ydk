"""Shared helpers for GitLab repository implementations."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

from ydk.models.pm import TaskStatus

if TYPE_CHECKING:
    import builtins
    from collections.abc import Callable

# glab defaults to 30 results per page for `issue list`; 100 is the API maximum.
GLAB_PAGE_SIZE = 100
GLAB_MAX_PAGES = 100


def run_glab(cmd: builtins.list[str]) -> subprocess.CompletedProcess[str]:
    """Execute a glab CLI command. Extracted for easy mocking."""
    return subprocess.run(cmd, capture_output=True, text=True)


def check_result(result: subprocess.CompletedProcess[str], action: str) -> None:
    """Raise RuntimeError if the glab command failed."""
    if result.returncode != 0:
        msg = f"glab {action} failed: {result.stderr.strip()}"
        raise RuntimeError(msg)


def glab_state(status: str) -> str:
    """Map generic status string to glab's ``--state`` value."""
    return "opened" if status == "open" else status


def map_status(glab_state_str: str) -> TaskStatus:
    """Convert GitLab issue state to our enum."""
    if glab_state_str in ("opened", "open"):
        return TaskStatus.OPEN
    if glab_state_str in ("closed", "done"):
        return TaskStatus.DONE
    return TaskStatus.OPEN


def extract_label_names(raw_labels: list) -> list[str]:
    """Extract label name strings from glab JSON label data."""
    label_names: list[str] = []
    for lbl in raw_labels:
        if isinstance(lbl, dict):
            label_names.append(lbl.get("name", ""))
        else:
            label_names.append(str(lbl))
    return label_names


def list_glab_issues(
    run: Callable[[builtins.list[str]], subprocess.CompletedProcess[str]],
    cmd: builtins.list[str],
) -> builtins.list[dict]:
    """Run a ``glab issue list`` command page by page and return all issues.

    Returns ``[]`` if any page fails or yields malformed JSON.
    """
    issues: builtins.list[dict] = []
    for page in range(1, GLAB_MAX_PAGES + 1):
        result = run([*cmd, "--per-page", str(GLAB_PAGE_SIZE), "--page", str(page)])
        if result.returncode != 0:
            return []
        try:
            batch = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []
        issues.extend(batch)
        if len(batch) < GLAB_PAGE_SIZE:
            break
    return issues

"""Shared helpers for GitHub repository implementations."""

from __future__ import annotations

import json
import subprocess
from typing import Any

# Parsed gh/glab JSON is untyped (object or array); callers narrow it.
JsonValue = Any

GH_JSON_FIELDS = "number,title,state,labels,body,url"

# gh defaults to 30 results for `issue list`; pass an explicit ceiling so lists are not silently truncated.
GH_LIST_LIMIT = 1000


def run_gh(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a gh CLI command and return the result."""
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def check_result(result: subprocess.CompletedProcess[str], action: str) -> None:
    """Raise RuntimeError if the gh command failed."""
    if result.returncode != 0:
        msg = f"gh {action} failed: {result.stderr.strip()}"
        raise RuntimeError(msg)


def load_json_stdout(result: subprocess.CompletedProcess[str], action: str) -> JsonValue:
    """Parse JSON from a gh result, raising RuntimeError if stdout is None/empty."""
    if result.stdout is None or not result.stdout.strip():
        msg = f"gh {action} returned no output: {(result.stderr or '').strip()}"
        raise RuntimeError(msg)
    return json.loads(result.stdout)


def label_names(raw_labels: list[dict]) -> list[str]:
    """Extract label name strings from the gh JSON label objects."""
    return [lbl["name"] for lbl in raw_labels if isinstance(lbl, dict) and "name" in lbl]


# Single source of truth for labels YDK relies on. Used by `ydk init`, `ydk task
# create-batch`, and `ydk doctor` so the three never disagree about names/colors again.
REQUIRED_LABELS: list[tuple[str, str, str]] = [
    ("epic", "0052cc", "Epic-level work item"),
    ("story", "2ea44f", "Story-level work item"),
    ("task", "fbca04", "Task-level work item"),
    ("in-progress", "6f42c1", "Work actively in progress"),
    ("in-review", "1d76db", "Work in code review"),
    ("blocked-by-code", "d73a4a", "Blocked by unmerged code dependency"),
    ("blocked-by-decision", "e99695", "Blocked pending a decision"),
]

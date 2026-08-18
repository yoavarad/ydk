"""Shared helpers for GitLab repository implementations."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from ydk.models.pm import TaskStatus

if TYPE_CHECKING:
    import builtins


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

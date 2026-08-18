"""Shared helpers for GitHub repository implementations."""

from __future__ import annotations

import subprocess

GH_JSON_FIELDS = "number,title,state,labels,body,url"


def run_gh(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a gh CLI command and return the result."""
    return subprocess.run(cmd, capture_output=True, text=True)


def check_result(result: subprocess.CompletedProcess[str], action: str) -> None:
    """Raise RuntimeError if the gh command failed."""
    if result.returncode != 0:
        msg = f"gh {action} failed: {result.stderr.strip()}"
        raise RuntimeError(msg)


def label_names(raw_labels: list[dict]) -> list[str]:
    """Extract label name strings from the gh JSON label objects."""
    return [lbl["name"] for lbl in raw_labels if isinstance(lbl, dict) and "name" in lbl]

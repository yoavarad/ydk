"""Shared gh helpers for the gh-issue-to-tasks scripts. Only the gh CLI is used."""

from __future__ import annotations

import json
import subprocess
import sys

MARKER_PREFIX = "<!-- ydk-gh-issue-to-tasks"
LINK_LABEL = "ydk-linked"


def gh(*args: str) -> str:
    """Run `gh` and return stdout; raise RuntimeError with stderr on failure."""
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def gh_json(*args: str) -> dict | list:
    """Run `gh` and parse stdout as JSON."""
    return json.loads(gh(*args))


def gh_obj(*args: str) -> dict:
    """Run `gh` and parse stdout as a JSON object."""
    data = gh_json(*args)
    if not isinstance(data, dict):
        raise RuntimeError(f"gh {' '.join(args)} did not return a JSON object")
    return data


def marker(kind: str, issue: int, extra: str = "") -> str:
    """Build the hidden idempotency marker embedded in comment bodies."""
    tail = f" {extra}" if extra else ""
    return f"{MARKER_PREFIX}:{kind} issue={issue}{tail} -->"


def find_comment(issue: int, kind: str) -> str | None:
    """Return the body of the first comment carrying the marker of this kind, else None."""
    data = gh_obj("issue", "view", str(issue), "--json", "comments")
    needle = f"{MARKER_PREFIX}:{kind} issue={issue}"
    for comment in data.get("comments", []):
        body = comment.get("body", "")
        if needle in body:
            return body
    return None


def post_comment_once(issue: int, kind: str, body: str, extra: str = "") -> bool:
    """Post `body` with a marker unless one of this kind already exists. Return True if posted."""
    if find_comment(issue, kind) is not None:
        return False
    gh("issue", "comment", str(issue), "--body", f"{body}\n\n{marker(kind, issue, extra)}")
    return True


def fail(message: str) -> int:
    """Print an error to stderr and return exit code 1."""
    print(message, file=sys.stderr)
    return 1

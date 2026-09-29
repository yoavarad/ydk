"""Retire external GitHub issues once every YDK task linked to them is closed."""

from __future__ import annotations

import json
import re

from ydk.repositories.github._helpers import GH_LIST_LIMIT, check_result, run_gh

MARKER_PREFIX = "<!-- ydk-gh-issue-to-tasks"
LINK_LABEL = "ydk-linked"
RETIRE_LABEL = "superseded"

_TASKS_RE = re.compile(r"tasks=([\w,-]+)")


def _gh(*args: str) -> str:
    """Run `gh` and return stdout; raise RuntimeError with stderr on failure."""
    result = run_gh(["gh", *args])
    check_result(result, " ".join(args))
    return result.stdout


def _loads(raw: str, *args: str) -> dict | list:
    """Parse gh JSON output; raise RuntimeError on malformed input."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh {' '.join(args)} returned invalid JSON: {exc}") from exc


def _gh_obj(*args: str) -> dict:
    data = _loads(_gh(*args), *args)
    if not isinstance(data, dict):
        raise RuntimeError(f"gh {' '.join(args)} did not return a JSON object")
    return data


def _marker(kind: str, issue: int) -> str:
    return f"{MARKER_PREFIX}:{kind} issue={issue} -->"


def _find_comment(issue: int, kind: str) -> str | None:
    data = _gh_obj("issue", "view", str(issue), "--json", "comments")
    needle = f"{MARKER_PREFIX}:{kind} issue={issue}"
    for comment in data.get("comments", []):
        body = comment.get("body", "")
        if needle in body:
            return body
    return None


def linked_tasks(issue: int) -> list[str]:
    """Task ids recorded in the issue's link marker."""
    match = _TASKS_RE.search(_find_comment(issue, "link") or "")
    return match.group(1).split(",") if match else []


def task_done(task_id: str) -> bool:
    """A task is done when its GitHub issue is closed."""
    return _gh_obj("issue", "view", task_id, "--json", "state").get("state") == "CLOSED"


def retire(issue: int, pointer: str = "") -> bool:
    """Comment (once), label and close as not planned. Return True if a comment was posted.

    Steps are idempotent, not atomic: if a later step fails (RuntimeError), earlier ones stay applied,
    and re-running finishes the remainder without duplicating the comment.
    """
    text = "Superseded by YDK tasks tracked separately; see the linking comment above."
    if pointer:
        text = f"{text}\n\n{pointer}"
    posted = False
    if _find_comment(issue, "retire") is None:
        _gh("issue", "comment", str(issue), "--body", f"{text}\n\n{_marker('retire', issue)}")
        posted = True
    _gh("issue", "edit", str(issue), "--add-label", RETIRE_LABEL)
    if _gh_obj("issue", "view", str(issue), "--json", "state").get("state") != "CLOSED":
        _gh("issue", "close", str(issue), "--reason", "not planned")
    return posted


def sync(dry_run: bool = False) -> list[int]:
    """Retire issues whose tasks are all done. Return the retired (or would-be retired) issue numbers."""
    list_args = ("issue", "list", "--label", LINK_LABEL, "--state", "open", "--json", "number", "--limit")
    list_args += (str(GH_LIST_LIMIT),)
    items = _loads(_gh(*list_args), *list_args)
    if not isinstance(items, list):
        raise RuntimeError("gh issue list did not return a JSON array")
    retired: list[int] = []
    for item in items:
        number = item["number"]
        tasks = linked_tasks(number)
        if tasks and all(task_done(t) for t in tasks):
            if not dry_run:
                retire(number, "All linked tasks are complete: " + ", ".join(f"#{t}" for t in tasks))
            retired.append(number)
    return retired

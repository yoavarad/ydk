"""Retire every linked issue whose YDK tasks (GitHub issues) are all closed."""

from __future__ import annotations

import argparse
import re

from _gh import LINK_LABEL, fail, find_comment, gh_json, gh_obj
from retire_issue import retire

TASKS_RE = re.compile(r"tasks=([\w,-]+)")


def linked_tasks(issue: int) -> list[str]:
    """Task ids recorded in the issue's link marker."""
    match = TASKS_RE.search(find_comment(issue, "link") or "")
    return match.group(1).split(",") if match else []


def task_done(task_id: str) -> bool:
    """A task is done when its GitHub issue is closed."""
    return gh_obj("issue", "view", task_id, "--json", "state").get("state") == "CLOSED"


def sync(dry_run: bool = False) -> list[int]:
    """Retire issues whose tasks are all done. Return the retired (or would-be retired) issue numbers."""
    issues = gh_json("issue", "list", "--label", LINK_LABEL, "--state", "open", "--json", "number")
    retired: list[int] = []
    for item in issues:
        number = item["number"]
        tasks = linked_tasks(number)
        if tasks and all(task_done(t) for t in tasks):
            if not dry_run:
                retire(number, "All linked tasks are complete: " + ", ".join(f"#{t}" for t in tasks))
            retired.append(number)
    return retired


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        retired = sync(args.dry_run)
    except RuntimeError as exc:
        return fail(str(exc))
    print("retired: " + (", ".join(f"#{n}" for n in retired) or "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

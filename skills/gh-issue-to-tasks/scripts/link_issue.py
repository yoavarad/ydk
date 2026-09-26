"""Comment on the source issue with the created YDK tasks and label it as linked. Idempotent."""

from __future__ import annotations

import argparse

from _gh import LINK_LABEL, fail, gh, post_comment_once


def build_body(tasks: list[str], plan: str) -> str:
    """Compose the linking comment."""
    lines = ["This issue has been triaged into YDK tasks:", ""]
    lines += [f"- Task #{t}" for t in tasks]
    if plan:
        lines += ["", plan]
    return "\n".join(lines)


def link(issue: int, tasks: list[str], plan: str = "") -> bool:
    """Post the linking comment once and apply the label. Return True if a comment was posted."""
    posted = post_comment_once(issue, "link", build_body(tasks, plan), extra=f"tasks={','.join(tasks)}")
    gh("issue", "edit", str(issue), "--add-label", LINK_LABEL)
    return posted


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("issue", type=int)
    parser.add_argument("tasks", nargs="+", help="YDK task ids")
    parser.add_argument("--plan", default="", help="Plan text to include in the comment")
    args = parser.parse_args(argv)
    try:
        posted = link(args.issue, args.tasks, args.plan)
    except RuntimeError as exc:
        return fail(str(exc))
    print("commented" if posted else "already linked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

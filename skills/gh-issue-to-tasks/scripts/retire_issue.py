"""Retire a triaged issue: pointer comment + label + close as not planned. Hard delete is opt-in, admin only."""

from __future__ import annotations

import argparse

from _gh import fail, gh, gh_obj, post_comment_once

RETIRE_LABEL = "superseded"
DELETE_MUTATION = "mutation($id:ID!){deleteIssue(input:{issueId:$id}){clientMutationId}}"


def is_admin() -> bool:
    """True when the authenticated user has admin permission on the current repo."""
    return gh_obj("repo", "view", "--json", "viewerPermission").get("viewerPermission") == "ADMIN"


def retire(issue: int, pointer: str = "") -> bool:
    """Comment (once), label and close. Return True if a comment was posted."""
    text = "Superseded by YDK tasks tracked separately; see the linking comment above."
    if pointer:
        text = f"{text}\n\n{pointer}"
    posted = post_comment_once(issue, "retire", text)
    gh("issue", "edit", str(issue), "--add-label", RETIRE_LABEL)
    if gh_obj("issue", "view", str(issue), "--json", "state").get("state") != "CLOSED":
        gh("issue", "close", str(issue), "--reason", "not planned")
    return posted


def delete(issue: int) -> None:
    """Hard delete via GraphQL. Requires admin; caller must have obtained explicit confirmation."""
    if not is_admin():
        raise PermissionError("hard delete requires repo admin permission")
    node_id = gh_obj("issue", "view", str(issue), "--json", "id")["id"]
    gh("api", "graphql", "-f", f"query={DELETE_MUTATION}", "-f", f"id={node_id}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("issue", type=int)
    parser.add_argument("--pointer", default="", help="Extra pointer text (task/PR links)")
    parser.add_argument("--delete", action="store_true", help="Hard delete (admin only, needs --confirm)")
    parser.add_argument("--confirm", action="store_true", help="Explicit user confirmation for --delete")
    args = parser.parse_args(argv)
    try:
        if args.delete:
            if not args.confirm:
                return fail("--delete requires --confirm (explicit user confirmation)")
            delete(args.issue)
            print("deleted")
            return 0
        posted = retire(args.issue, args.pointer)
    except (RuntimeError, PermissionError) as exc:
        return fail(str(exc))
    print("retired" if posted else "already retired")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

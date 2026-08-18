"""Commit-msg hook — validates conventional commit format.

Expected format::

    type(scope): description
    type: description

Valid types: feat, fix, docs, chore, refactor, test, ci, perf, release, bump.
Scope is optional but must be non-empty when present.
"""

from __future__ import annotations

import re
import sys

VALID_TYPES = frozenset(
    {
        "feat",
        "fix",
        "docs",
        "chore",
        "refactor",
        "test",
        "ci",
        "perf",
        "release",
        "bump",
    }
)

_PATTERN = re.compile(
    r"^(?P<type>[a-z]+)"  # type
    r"(?:\((?P<scope>[a-zA-Z0-9_-]+)\))?"  # optional (scope)
    r":\s(?P<desc>.+)$",  # : description
)


def validate_commit_message(message: str) -> bool:
    """Return *True* if the first line of *message* matches conventional-commit format."""
    first_line = message.split("\n", 1)[0].strip()
    if not first_line:
        return False

    match = _PATTERN.match(first_line)
    if match is None:
        return False

    return match.group("type") in VALID_TYPES


def main() -> None:
    """Entry point when invoked as a git commit-msg hook.

    Git passes the path to the temporary commit-message file as the first
    argument.
    """
    if len(sys.argv) < 2:
        print("commit-msg hook: missing message file argument", file=sys.stderr)
        sys.exit(1)

    msg_file = sys.argv[1]
    with open(msg_file) as fh:
        message = fh.read()

    if not validate_commit_message(message):
        print(
            "commit-msg hook: message does not follow conventional commit format.\n"
            "Expected: type(scope): description  or  type: description\n"
            f"Valid types: {', '.join(sorted(VALID_TYPES))}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()

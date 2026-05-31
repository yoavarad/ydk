#!/usr/bin/env python3
"""Guard plugin: block manual PR creation.

PRs must be created via `odk task done` to capture verification proof.
"""

import json
import sys


def main() -> None:
    """Run the guard-no-manual-pr check."""
    try:
        raw = sys.stdin.read()
        context = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        print(
            json.dumps({"name": "guard-no-manual-pr", "passed": True, "output": "PASS: stdin parse failed (fail open)"})
        )
        return
    command = context.get("command", "")

    if "gh pr create" in command or "gh pr merge" in command:
        result = {
            "name": "guard-no-manual-pr",
            "passed": False,
            "output": "BLOCKED: Use `odk task done` to create PRs — it captures verification proof.",
            "duration_seconds": 0.0,
        }
        json.dump(result, sys.stdout)
        sys.exit(1)

    result = {
        "name": "guard-no-manual-pr",
        "passed": True,
        "output": "OK",
        "duration_seconds": 0.0,
    }
    json.dump(result, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()

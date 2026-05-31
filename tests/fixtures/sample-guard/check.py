#!/usr/bin/env python3
"""Sample guard plugin: blocks edits to files under blocked/ directory."""

import json
import sys


def main() -> None:
    context = json.loads(sys.stdin.read())
    file_path = context.get("file_path", "")

    if file_path.startswith("blocked/"):
        result = {
            "name": "sample-guard",
            "passed": False,
            "output": f"BLOCKED: edits to '{file_path}' are not allowed (blocked/ directory)",
            "duration_seconds": 0.0,
        }
    else:
        result = {
            "name": "sample-guard",
            "passed": True,
            "output": "OK",
            "duration_seconds": 0.0,
        }

    json.dump(result, sys.stdout)
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Verification plugin: CLI commands must catch ApiError from HTTP client calls."""

import json
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the cli-error-handling verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    commands_dir = root / "src" / "commands"

    if not commands_dir.is_dir():
        result = {
            "name": "cli-error-handling",
            "passed": True,
            "output": "PASS: no src/commands/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    failures = 0
    messages: list[str] = []

    for py_file in commands_dir.rglob("*.py"):
        if py_file.name.startswith("__"):
            continue
        try:
            content = py_file.read_text()
            if "client.request" in content and "ApiError" not in content:
                messages.append(f"FAIL: {py_file} -- must catch ApiError from HTTP client calls")
                failures += 1
        except OSError:
            pass

    passed = failures == 0
    output = "PASS: all commands handle HTTP errors" if passed else "\n".join(messages)

    result = {
        "name": "cli-error-handling",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Verification plugin: TDD enforcement -- staged source files must have test files."""

import json
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the python-tdd-guard verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    config = context.get("config", {})
    staged_files = config.get("staged_files", [])
    start = time.time()

    root = Path(project_root)
    failures = 0
    messages: list[str] = []

    for filepath in staged_files:
        # Only check src/**/*.py files
        if not filepath.startswith("src/") or not filepath.endswith(".py"):
            continue

        # Skip exempted paths
        basename = Path(filepath).name
        if any(pat in filepath for pat in ["__init__", "conftest", "/migrations/", "/ports/", "/tests/"]):
            continue

        test_name = f"test_{basename}"
        tests_dir = root / "tests"

        # Search for test file
        found = list(tests_dir.rglob(test_name)) if tests_dir.is_dir() else []
        if not found:
            messages.append(f"FAIL: {filepath} -- {test_name} not found in tests/")
            failures += 1

    passed = failures == 0
    if passed:
        output = "PASS: all staged source files have test files"
    else:
        output = "\n".join(messages) + f"\nTDD: {failures} file(s) missing tests."

    result = {
        "name": "python-tdd-guard",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

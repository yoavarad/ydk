#!/usr/bin/env python3
"""Verification plugin: TDD enforcement -- staged .cs source files must have test files."""

import json
import os
import sys
import time
from pathlib import Path

# Directories that are never worth walking into while searching for test files.
_EXCLUDED_DIRS = {".git", "bin", "obj", "node_modules", ".venv", ".ydk"}


def _is_test_dir_part(part: str) -> bool:
    """True if a path segment names a test project/directory (``Tests`` or ``*.Tests``)."""
    return part == "Tests" or part.endswith(".Tests")


def _is_already_test_file(filepath: str) -> bool:
    """True if the staged file already lives inside a test project/directory."""
    parts = Path(filepath).parts[:-1]
    return any(_is_test_dir_part(part) for part in parts)


def _find_test_file(root: Path, test_name: str) -> bool:
    """Search the repo tree for ``test_name`` under any Tests-named directory."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIRS]
        if test_name not in filenames:
            continue
        rel_parts = Path(dirpath).relative_to(root).parts
        if any(_is_test_dir_part(part) for part in rel_parts):
            return True
    return False


def main() -> None:
    """Run the dotnet-tdd-guard verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    config = context.get("config", {})
    staged_files = config.get("staged_files", [])
    start = time.time()

    root = Path(project_root)
    failures = 0
    messages: list[str] = []

    for filepath in staged_files:
        if not filepath.endswith(".cs"):
            continue

        # Skip files that already live inside a test project -- don't demand a test for a test.
        if _is_already_test_file(filepath):
            continue

        stem = Path(filepath).stem
        test_name = f"{stem}Tests.cs"

        if not _find_test_file(root, test_name):
            messages.append(f"FAIL: {filepath} -- {test_name} not found")
            failures += 1

    passed = failures == 0
    if passed:
        output = "PASS: all staged source files have test files"
    else:
        output = "\n".join(messages) + f"\nTDD: {failures} file(s) missing tests."

    result = {
        "name": "dotnet-tdd-guard",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

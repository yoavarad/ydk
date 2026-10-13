#!/usr/bin/env python3
"""Verification plugin: TDD enforcement -- staged source files must have test files."""

import json
import sys
import time
from pathlib import Path, PurePosixPath


def _matches(filepath: str, globs: list[str]) -> bool:
    return any(PurePosixPath(filepath).full_match(g) for g in globs)


def _is_guarded(filepath: str, tdd: dict) -> bool:
    """True if filepath is a source file this plugin should check."""
    is_vendor = filepath.startswith("vendor/") or "/vendor/" in filepath
    if (tdd and is_vendor) or _matches(filepath, tdd.get("exempt_globs") or []):
        return False
    same_dir = tdd.get("test_for") == "same-dir-suffix"
    if same_dir and filepath.endswith(tdd.get("test_suffix") or "_test.go"):
        return False
    if tdd.get("test_globs") is not None and _matches(filepath, tdd["test_globs"]):
        return False
    if tdd.get("source_globs") is not None:
        name = Path(filepath).name
        if tdd.get("test_globs") is None and (
            filepath.startswith("tests/") or name.startswith("test_") or name.endswith("_test.py")
        ):
            return False
        skip = ["__init__", "conftest", "/migrations/", "/ports/", "/tests/"]
        return _matches(filepath, tdd["source_globs"]) and not any(pat in filepath for pat in skip)
    # Legacy: only src/**/*.py
    if not filepath.startswith("src/") or not filepath.endswith(".py"):
        return False
    return not any(pat in filepath for pat in ["__init__", "conftest", "/migrations/", "/ports/", "/tests/"])


def main() -> None:
    """Run the python-tdd-guard verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    config = context.get("config", {})
    staged_files = config.get("staged_files", [])
    tdd = config.get("tdd") or {}
    start = time.time()

    root = Path(project_root)
    failures = 0
    messages: list[str] = []

    for filepath in staged_files:
        if not _is_guarded(filepath, tdd):
            continue

        basename = Path(filepath).name
        if tdd.get("test_for") == "same-dir-suffix":
            suffix = tdd.get("test_suffix") or "_test.go"
            test_name = f"{Path(filepath).stem}{suffix}"
            directory = (root / filepath).parent
            if not (directory / test_name).exists() and not (directory.is_dir() and any(directory.glob(f"*{suffix}"))):
                messages.append(f"FAIL: {filepath} -- {test_name} (or any *{suffix}) not found in same directory")
                failures += 1
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

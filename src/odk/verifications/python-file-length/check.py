#!/usr/bin/env python3
"""Verification plugin: no Python file exceeds 300 lines (except tests, migrations, generated)."""

import json
import re
import sys
import time
from pathlib import Path

LIMIT = 300

EXEMPT_PATTERNS = [
    "/tests/",
    "/alembic/versions/",
    "/__pycache__/",
    "/.venv/",
    "/.odk/",
]


def is_stub(content: str) -> bool:
    """Check if file is a generated stub."""
    return bool(re.search(r"raise NotImplementedError|# TODO\[odk:", content))


def main() -> None:
    """Run the python-file-length verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    app_dir = root / "app"

    if not app_dir.is_dir():
        result = {
            "name": "python-file-length",
            "passed": True,
            "output": "PASS: no app/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    failures = 0
    messages: list[str] = []

    for py_file in app_dir.rglob("*.py"):
        fpath = str(py_file)

        # Skip exempt paths
        if any(pat in fpath for pat in EXEMPT_PATTERNS):
            continue

        try:
            content = py_file.read_text()
        except OSError:
            continue

        # Skip stubs
        if is_stub(content):
            continue

        line_count = len(content.splitlines())
        if line_count > LIMIT:
            messages.append(
                f"FAIL: {py_file} has {line_count} lines (max {LIMIT})\n"
                "  Split into smaller modules with single responsibility"
            )
            failures += 1

    passed = failures == 0
    if passed:
        output = "PASS: all Python files within line limits"
    else:
        output = "\n".join(messages) + f"\n{failures} file(s) exceed line limit"

    result = {
        "name": "python-file-length",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

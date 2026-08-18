#!/usr/bin/env python3
"""Verification plugin: no mock imports in tests/integration/."""

import json
import re
import sys
import time
from pathlib import Path

MOCK_PATTERNS = [
    r"unittest\.mock",
    r"from unittest import mock",
    r"@patch",
    r"MagicMock",
    r"Mock\(\)",
    r"mock\.patch\(",
]


def main() -> None:
    """Run the fastapi-no-mocks-integration verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    int_dir = root / "tests" / "integration"

    if not int_dir.is_dir():
        result = {
            "name": "fastapi-no-mocks-integration",
            "passed": True,
            "output": "PASS: no tests/integration/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    combined_pattern = "|".join(MOCK_PATTERNS)
    violations: list[str] = []

    for py_file in int_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            for i, line in enumerate(py_file.read_text().splitlines(), 1):
                if re.search(combined_pattern, line):
                    violations.append(f"{py_file}:{i}: {line.strip()}")
        except OSError:
            pass

    passed = len(violations) == 0
    if passed:
        output = "PASS: no mocks in tests/integration/"
    else:
        output = (
            "FAIL: Mocking not allowed in integration tests:\n"
            + "\n".join(violations)
            + "\n\n  Integration tests must use app.dependency_overrides instead of mocks."
        )

    result = {
        "name": "fastapi-no-mocks-integration",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"violations": len(violations)},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Verification plugin: no mock imports in tests/e2e/."""

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
    r"patch\(",
]


def main() -> None:
    """Run the fastapi-no-mocks-e2e verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    e2e_dir = root / "tests" / "e2e"

    if not e2e_dir.is_dir():
        result = {
            "name": "fastapi-no-mocks-e2e",
            "passed": True,
            "output": "PASS: no tests/e2e/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    combined_pattern = "|".join(MOCK_PATTERNS)
    violations: list[str] = []

    for py_file in e2e_dir.rglob("*.py"):
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
        output = "PASS: no mocks in tests/e2e/"
    else:
        output = (
            "FAIL: Mocking not allowed in E2E tests:\n"
            + "\n".join(violations)
            + "\n\n  E2E tests must exercise real behavior. Use the http_client fixture."
        )

    result = {
        "name": "fastapi-no-mocks-e2e",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"violations": len(violations)},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

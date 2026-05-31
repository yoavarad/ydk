#!/usr/bin/env python3
"""Verification plugin: route files must be split by domain -- max 150 lines each."""

import json
import sys
import time
from pathlib import Path

LIMIT = 150


def main() -> None:
    """Run the fastapi-route-splitting verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    routes_dir = root / "app" / "api" / "routes"

    if not routes_dir.is_dir():
        result = {
            "name": "fastapi-route-splitting",
            "passed": True,
            "output": "PASS: no app/api/routes/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    failures = 0
    messages: list[str] = []

    for py_file in routes_dir.rglob("*.py"):
        if py_file.name == "__init__.py" or "__pycache__" in str(py_file):
            continue
        try:
            line_count = len(py_file.read_text().splitlines())
            if line_count > LIMIT:
                messages.append(
                    f"FAIL: {py_file} has {line_count} lines (max {LIMIT} per route file)\n"
                    "  Split routes by domain: strategies.py, backtest.py, dashboard.py, etc."
                )
                failures += 1
        except OSError:
            pass

    passed = failures == 0
    if passed:
        output = "PASS: all route files within line limits"
    else:
        output = "\n".join(messages) + "\nRoute files too large -- split by domain"

    result = {
        "name": "fastapi-route-splitting",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

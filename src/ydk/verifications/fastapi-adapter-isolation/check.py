#!/usr/bin/env python3
"""Verification plugin: adapters must not import from app/api/."""

import json
import re
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the fastapi-adapter-isolation verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    adapters_dir = root / "app" / "adapters"

    if not adapters_dir.is_dir():
        result = {
            "name": "fastapi-adapter-isolation",
            "passed": True,
            "output": "PASS: no app/adapters/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    failures = 0
    messages: list[str] = []

    for py_file in adapters_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            for i, line in enumerate(py_file.read_text().splitlines(), 1):
                if re.search(r"from app\.api|import app\.api", line):
                    messages.append(
                        f"FAIL: {py_file}:{i} imports from app/api/ "
                        "(adapters must not depend on HTTP layer):\n  {line.strip()}"
                    )
                    failures += 1
        except OSError:
            pass

    passed = failures == 0
    if passed:
        output = "PASS: app/adapters/ isolation is clean"
    else:
        output = "\n".join(messages) + f"\nAdapter isolation: {failures} violation(s)"

    result = {
        "name": "fastapi-adapter-isolation",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

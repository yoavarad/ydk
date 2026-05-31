#!/usr/bin/env python3
"""Verification plugin: app/core/ must not import from app/adapters/ or app/api/."""

import json
import re
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the fastapi-core-purity verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    core_dir = root / "app" / "core"

    if not core_dir.is_dir():
        result = {
            "name": "fastapi-core-purity",
            "passed": True,
            "output": "PASS: no app/core/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    failures = 0
    messages: list[str] = []

    for py_file in core_dir.rglob("*.py"):
        fpath = str(py_file)
        if "__pycache__" in fpath:
            continue

        # Skip execution engine zones (exempt from core purity check)
        if "/app/strategies/" in fpath or "/app/workflows/" in fpath:
            continue

        try:
            for i, line in enumerate(py_file.read_text().splitlines(), 1):
                if re.search(
                    r"from app\.adapters|from app\.api|import app\.adapters|import app\.api",
                    line,
                ):
                    messages.append(
                        f"FAIL: {py_file}:{i} violates hexagonal core purity:\n  {line.strip()}\n"
                        "  app/core/ must ONLY import from app/core/ (ports, models, other services).\n"
                        "  Adapters and API handlers are injected -- never imported directly."
                    )
                    failures += 1
        except OSError:
            pass

    passed = failures == 0
    if passed:
        output = "PASS: app/core/ is architecturally clean"
    else:
        output = "\n".join(messages) + f"\nCore purity: {failures} violation(s)"

    result = {
        "name": "fastapi-core-purity",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

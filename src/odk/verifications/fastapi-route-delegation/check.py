#!/usr/bin/env python3
"""Verification plugin: API routes must delegate to services, not import adapters directly."""

import json
import re
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the fastapi-route-delegation verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    routes_dir = root / "app" / "api" / "routes"

    if not routes_dir.is_dir():
        result = {
            "name": "fastapi-route-delegation",
            "passed": True,
            "output": "PASS: no app/api/routes/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    warnings: list[str] = []

    for py_file in routes_dir.rglob("*.py"):
        if py_file.name == "__init__.py" or "__pycache__" in str(py_file):
            continue
        try:
            for i, line in enumerate(py_file.read_text().splitlines(), 1):
                if "# odk:allow-route-import" in line:
                    continue
                if re.search(r"from app\.adapters|from sqlalchemy.*import.*AsyncSession", line):
                    warnings.append(
                        f"WARN: {py_file}:{i} may have direct adapter/session access "
                        "(routes should use Depends()):\n  {line.strip()}\n"
                        "  Routes must delegate to services via FastAPI Depends(). "
                        "Never import adapters directly."
                    )
        except OSError:
            pass

    # Original script is warning-only (always returns 0)
    passed = True
    output = "\n".join(warnings) if warnings else "PASS: all routes delegate correctly"

    result = {
        "name": "fastapi-route-delegation",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"warnings": len(warnings)},
    }
    json.dump(result, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()

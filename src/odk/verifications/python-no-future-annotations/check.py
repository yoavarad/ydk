#!/usr/bin/env python3
"""Verification plugin: no 'from __future__ import annotations' in route files.

FastAPI uses runtime type introspection for dependency injection and parameter
resolution. The future annotations import converts all annotations to strings,
breaking FastAPI's Query/Path/Body parameter detection.
"""

import json
import re
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the python-no-future-annotations verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    routes_dir = root / "app" / "api" / "routes"

    if not routes_dir.is_dir():
        result = {
            "name": "python-no-future-annotations",
            "passed": True,
            "output": "PASS: no app/api/routes/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    violations: list[str] = []
    for py_file in routes_dir.rglob("*.py"):
        try:
            for i, line in enumerate(py_file.read_text().splitlines(), 1):
                if re.match(r"^from __future__ import annotations", line):
                    violations.append(f"{py_file}:{i}: {line}")
        except OSError:
            pass

    passed = len(violations) == 0
    if passed:
        output = "PASS: no 'from __future__ import annotations' in route files"
    else:
        output = (
            "FAIL: 'from __future__ import annotations' found in route files:\n"
            + "\n".join(violations)
            + "\n\n  This import breaks FastAPI's runtime type resolution for Query/Path/Body params.\n"
            "  Remove the import -- use 'X | None' syntax instead of Optional[X]."
        )

    result = {
        "name": "python-no-future-annotations",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"violations": len(violations)},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

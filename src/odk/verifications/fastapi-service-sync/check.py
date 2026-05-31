#!/usr/bin/env python3
"""Verification plugin: services must be synchronous. No async def allowed."""

import json
import re
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the fastapi-service-sync verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    services_dir = root / "app" / "core" / "services"

    if not services_dir.is_dir():
        result = {
            "name": "fastapi-service-sync",
            "passed": True,
            "output": "PASS: no app/core/services/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    failures = 0
    messages: list[str] = []

    for py_file in services_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        # Port services are allowed to be async (they delegate to async adapters)
        rel_path = str(py_file.relative_to(root))
        if "_port_service/" in rel_path or "_port_service.py" in rel_path:
            continue
        try:
            content = py_file.read_text()
            # Check class name: PortService classes are allowed async
            if "PortService" in content:
                continue
            for i, line in enumerate(content.splitlines(), 1):
                if re.match(r"\s*async def", line) and "# odk:allow-async" not in line:
                    messages.append(
                        f"FAIL: {py_file}:{i} has async def (services must be synchronous):\n"
                        f"  {line.strip()}\n"
                        "  Fix: remove async def. Use asyncio.run() in adapters for async I/O.\n"
                        "  Suppress: append  # odk:allow-async  on that line if truly needed."
                    )
                    failures += 1
        except OSError:
            pass

    passed = failures == 0
    if passed:
        output = "PASS: no async def in app/core/services/"
    else:
        output = "\n".join(messages) + f"\nService sync enforcement: {failures} violation(s)"

    result = {
        "name": "fastapi-service-sync",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

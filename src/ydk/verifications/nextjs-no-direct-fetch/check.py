#!/usr/bin/env python3
"""Verification plugin: no raw HTTP calls outside src/shared/api/."""

import json
import re
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the nextjs-no-direct-fetch verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    src_dir = root / "src"

    if not src_dir.is_dir():
        result = {
            "name": "nextjs-no-direct-fetch",
            "passed": True,
            "output": "PASS: no src/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    failures = 0
    messages: list[str] = []
    pattern = re.compile(r"\bfetch\s*\(|new XMLHttpRequest\s*\(|axios\.(get|post|put|delete|patch)\s*\(")

    for ext in ("*.ts", "*.tsx"):
        for f in src_dir.rglob(ext):
            fpath = str(f)
            if "node_modules" in fpath or "/generated/" in fpath:
                continue
            # Allowed in shared/api/ and shared/lib/api/
            if "/src/shared/api/" in fpath or "/src/shared/lib/api/" in fpath:
                continue

            try:
                for i, line in enumerate(f.read_text().splitlines(), 1):
                    if pattern.search(line):
                        rel = str(f.relative_to(root))
                        messages.append(
                            f"FAIL: {rel}:{i} contains raw HTTP calls "
                            "(use @/shared/api/generated SDK):\n"
                            f"  {line.strip()}\n"
                            "  Fix: import the generated SDK function and wrap in useQuery/useMutation"
                        )
                        failures += 1
            except OSError:
                pass

    passed = failures == 0
    if passed:
        output = "PASS: no direct fetch/XHR/axios calls outside shared/api/"
    else:
        output = "\n".join(messages) + f"\n{failures} raw HTTP call(s) found"

    result = {
        "name": "nextjs-no-direct-fetch",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

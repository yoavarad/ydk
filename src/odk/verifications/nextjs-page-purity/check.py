#!/usr/bin/env python3
"""Verification plugin: app/ routing shells must not contain hooks."""

import json
import re
import sys
import time
from pathlib import Path

HOOK_PATTERNS = [
    "useState",
    "useEffect",
    "useQuery",
    "useMutation",
    "useCallback",
    "useMemo",
]


def main() -> None:
    """Run the nextjs-page-purity verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    app_dir = root / "src" / "app"

    if not app_dir.is_dir():
        result = {
            "name": "nextjs-page-purity",
            "passed": True,
            "output": "PASS: no src/app/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    failures = 0
    messages: list[str] = []
    pattern = "|".join(HOOK_PATTERNS)

    for ext in ("*.ts", "*.tsx"):
        for f in app_dir.rglob(ext):
            if "node_modules" in str(f):
                continue
            try:
                violations = []
                for i, line in enumerate(f.read_text().splitlines(), 1):
                    if re.search(pattern, line):
                        violations.append(f"  {i}: {line.strip()}")
                if violations:
                    rel = str(f.relative_to(root))
                    messages.append(
                        f"FAIL: {rel} (app/ routing shell) contains hooks:\n"
                        + "\n".join(violations)
                        + "\n  Move all logic to src/_pages/{{domain}}/{{Page}}Page.tsx"
                    )
                    failures += 1
            except OSError:
                pass

    passed = failures == 0
    output = "PASS: app/ pages are clean routing shells" if passed else "\n".join(messages)

    result = {
        "name": "nextjs-page-purity",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

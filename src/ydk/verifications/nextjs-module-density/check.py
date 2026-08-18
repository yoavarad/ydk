#!/usr/bin/env python3
"""Verification plugin: warn when directories have too many component files (advisory only)."""

import json
import sys
import time
from pathlib import Path

LIMIT = 12


def main() -> None:
    """Run the nextjs-module-density verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    src_dir = root / "src"

    if not src_dir.is_dir():
        result = {
            "name": "nextjs-module-density",
            "passed": True,
            "output": "PASS: no src/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    warnings: list[str] = []

    for d in src_dir.rglob("*"):
        if not d.is_dir():
            continue
        dpath = str(d)
        if "node_modules" in dpath or "/generated/" in dpath or "/components/ui/" in dpath or "/.ydk/" in dpath:
            continue

        # Count .ts/.tsx files (not index.ts) at this level only
        count = sum(1 for f in d.iterdir() if f.is_file() and f.suffix in (".ts", ".tsx") and f.name != "index.ts")
        if count > LIMIT:
            warnings.append(f"WARN: {d} has {count} files (max {LIMIT} -- consider sub-grouping)")

    # Advisory only -- always passes
    passed = True
    if warnings:
        output = "\n".join(warnings) + "\nPASS: module density check complete"
    else:
        output = "PASS: module density check complete"

    result = {
        "name": "nextjs-module-density",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"warnings": len(warnings)},
    }
    json.dump(result, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Verification plugin: FSD import boundaries via eslint-plugin-boundaries."""

import json
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the nextjs-fsd-layers verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)

    if not (root / "node_modules").is_dir():
        result = {
            "name": "nextjs-fsd-layers",
            "passed": True,
            "output": "WARN: node_modules not installed -- skipping FSD layer check. Run: bun install",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    proc = subprocess.run(
        ["bunx", "eslint", "--max-warnings", "0", "src/**/*.{ts,tsx}"],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    output_text = proc.stdout
    if proc.stderr:
        output_text += "\n" + proc.stderr

    passed = proc.returncode == 0
    output = "PASS: FSD boundaries" if passed else "FAIL: FSD layer violations found\n" + output_text.strip()

    result = {
        "name": "nextjs-fsd-layers",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": None,
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Verification plugin: no direct process.env usage outside shared/config/env.ts."""

import json
import re
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the nextjs-no-direct-env verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    src_dir = root / "src"

    if not src_dir.is_dir():
        result = {
            "name": "nextjs-no-direct-env",
            "passed": True,
            "output": "PASS: no src/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    failures = 0
    messages: list[str] = []

    for ext in ("*.ts", "*.tsx"):
        for f in src_dir.rglob(ext):
            fpath = str(f)
            if "node_modules" in fpath or "/generated/" in fpath:
                continue

            # Only the env module itself is allowed
            if fpath.endswith("shared/config/env.ts") or fpath.endswith("shared/lib/env.ts"):
                continue

            try:
                for i, line in enumerate(f.read_text().splitlines(), 1):
                    if re.search(r"process\.env(\.|(\[))", line) and "process.env.NODE_ENV" not in line:
                        rel = str(f.relative_to(root))
                        messages.append(
                            f"FAIL: {rel}:{i} reads process.env directly:\n"
                            f"  {line.strip()}\n"
                            "  Add the env var to src/shared/config/env.ts and import from there.\n"
                            "  Example: import {{ env }} from '@/shared/config/env'"
                        )
                        failures += 1
            except OSError:
                pass

    passed = failures == 0
    if passed:
        output = "PASS: no direct process.env usage"
    else:
        output = "\n".join(messages) + f"\n{failures} direct process.env usage(s)"

    result = {
        "name": "nextjs-no-direct-env",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Verification plugin: 'use client' files must not import Server Components."""

import json
import re
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the nextjs-server-client-boundary verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    src_dir = root / "src"

    if not src_dir.is_dir():
        result = {
            "name": "nextjs-server-client-boundary",
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
            if "node_modules" in str(f):
                continue
            try:
                content = f.read_text()
                lines = content.splitlines()

                # Check if this file is a Client Component
                first_lines = "\n".join(lines[:3])
                if "'use client'" not in first_lines and '"use client"' not in first_lines:
                    continue

                rel = str(f.relative_to(root))

                # Check for Server Action imports
                for i, line in enumerate(lines, 1):
                    if re.search(r"from ['\"].*actions['\"]", line):
                        messages.append(
                            f"FAIL: {rel}:{i} (Client Component) imports Server Actions directly:\n"
                            f"  {line.strip()}\n"
                            "  Wrap Server Actions in a form action or server-side event handler."
                        )
                        failures += 1

                # Check for imports from src/app/ routing segments
                for i, line in enumerate(lines, 1):
                    if re.search(
                        r"""from ['"]@/app/|from ['"]\.\.\/app\/|from ['"]\.\.\/\.\.\/app\/""",
                        line,
                    ):
                        messages.append(
                            f"FAIL: {rel}:{i} (Client Component) imports from src/app/ routing segments:\n"
                            f"  {line.strip()}\n"
                            "  Client Components cannot import Server Components.\n"
                            "  Pass server data as props instead."
                        )
                        failures += 1
            except OSError:
                pass

    passed = failures == 0
    output = "PASS: server/client boundary clean" if passed else "\n".join(messages)

    result = {
        "name": "nextjs-server-client-boundary",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

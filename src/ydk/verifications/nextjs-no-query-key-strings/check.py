#!/usr/bin/env python3
"""Verification plugin: TanStack Query key arrays must not contain raw string literals."""

import json
import re
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the nextjs-no-query-key-strings verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    src_dir = root / "src"

    if not src_dir.is_dir():
        result = {
            "name": "nextjs-no-query-key-strings",
            "passed": True,
            "output": "PASS: no src/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    failures = 0
    messages: list[str] = []
    pattern = re.compile(r"""queryKey\s*:\s*\[['"]|mutationKey\s*:\s*\[['"]""")

    for ext in ("*.ts", "*.tsx"):
        for f in src_dir.rglob(ext):
            fpath = str(f)
            if "node_modules" in fpath or "/generated/" in fpath:
                continue

            try:
                content = f.read_text()
                # Only check files that use TanStack Query
                if not re.search(r"useQuery|useMutation|useInfiniteQuery|queryClient", content):
                    continue

                for i, line in enumerate(content.splitlines(), 1):
                    if pattern.search(line):
                        rel = str(f.relative_to(root))
                        messages.append(
                            f"FAIL: {rel}:{i} uses inline string literals in query keys:\n"
                            f"  {line.strip()}\n"
                            "  Create a typed key factory in the entity model:\n"
                            "    export const userKeys = {\n"
                            "      all: ['users'] as const,\n"
                            "      list: () => [...userKeys.all, 'list'] as const,\n"
                            "      detail: (id: string) => [...userKeys.all, 'detail', id] as const,\n"
                            "    }"
                        )
                        failures += 1
            except OSError:
                pass

    passed = failures == 0
    if passed:
        output = "PASS: no inline string query keys"
    else:
        output = "\n".join(messages) + f"\n{failures} inline query key string(s) found"

    result = {
        "name": "nextjs-no-query-key-strings",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

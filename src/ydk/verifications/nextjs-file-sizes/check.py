#!/usr/bin/env python3
"""Verification plugin: per-FSD-layer file size limits."""

import json
import sys
import time
from pathlib import Path

# Layer limits: (path_pattern, limit, layer_name)
LAYER_LIMITS = [
    # Whitelist patterns (return None to skip)
    ("src/app/providers.tsx", None, None),
    ("src/app/providers.ts", None, None),
    ("src/app/layout.tsx", None, None),
    ("src/app/layout.ts", None, None),
    ("src/app/auth/callback/route.ts", None, None),
    ("src/app/auth/callback/route.tsx", None, None),
    ("src/shared/lib/sse/useEventStream.ts", None, None),
    ("src/shared/lib/sse/useEventStream.tsx", None, None),
    # Layer limits
    ("src/app/", 20, "app/ routing shell"),
    ("src/_pages/", 100, "_pages/ smart container"),
    ("src/widgets/", 150, "widgets/"),
    ("src/features/", 100, "features/"),
    ("src/entities/", 80, "entities/"),
    ("src/shared/", 120, "shared/"),
]


def get_limit(rel_path: str) -> tuple[int | None, str | None]:
    """Get the line limit for a file based on its FSD layer."""
    for pattern, limit, name in LAYER_LIMITS:
        if pattern.endswith("/"):
            if rel_path.startswith(pattern):
                return limit, name
        else:
            if rel_path == pattern:
                return limit, name
    return None, None


def main() -> None:
    """Run the nextjs-file-sizes verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    src_dir = root / "src"

    if not src_dir.is_dir():
        result = {
            "name": "nextjs-file-sizes",
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
            if "node_modules" in fpath or "/generated/" in fpath or "/components/ui/" in fpath:
                continue
            # Skip test files
            if "/__tests__/" in fpath or ".test." in fpath or ".spec." in fpath:
                continue

            rel = str(f.relative_to(root))
            limit, layer_name = get_limit(rel)
            if limit is None:
                continue

            try:
                line_count = len(f.read_text().splitlines())
                if line_count > limit:
                    messages.append(
                        f"FAIL: {rel} has {line_count} lines (max {limit} for {layer_name})\n"
                        "  Extract sub-components, hooks, or utilities to lower layers."
                    )
                    failures += 1
            except OSError:
                pass

    passed = failures == 0
    if passed:
        output = "PASS: all files within size limits"
    else:
        output = "\n".join(messages) + f"\n{failures} file(s) exceed size limits"

    result = {
        "name": "nextjs-file-sizes",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

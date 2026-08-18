#!/usr/bin/env python3
"""Verification plugin: Zustand stores must use factory pattern, not module-level singletons."""

import json
import re
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the nextjs-no-zustand-module-level verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    src_dir = root / "src"

    if not src_dir.is_dir():
        result = {
            "name": "nextjs-no-zustand-module-level",
            "passed": True,
            "output": "PASS: no src/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    failures = 0
    messages: list[str] = []
    pattern = re.compile(r"^export\s+(const|let)\s+use[A-Z][a-zA-Z]*\s*=\s*(create|createStore)\s*[<(]")

    for ext in ("*.ts", "*.tsx"):
        for f in src_dir.rglob(ext):
            fpath = str(f)
            if "node_modules" in fpath or "/generated/" in fpath:
                continue
            # Store infrastructure files are exempt
            if "/src/shared/store/" in fpath:
                continue
            if fpath.endswith("src/app/providers.tsx") or fpath.endswith("src/app/providers.ts"):
                continue

            try:
                content = f.read_text()
                # Only check files that import from zustand
                if not re.search(r"""from ['"]zustand""", content):
                    continue

                for i, line in enumerate(content.splitlines(), 1):
                    if pattern.search(line):
                        rel = str(f.relative_to(root))
                        messages.append(
                            f"FAIL: {rel}:{i} declares a module-level Zustand singleton:\n"
                            f"  {line.strip()}\n"
                            "  Use factory pattern: export const createXxxStore = () =>"
                            " createStore<...>()(initializer)\n"
                            "  Provide via context in src/app/providers.tsx to prevent SSR state leaks."
                        )
                        failures += 1
            except OSError:
                pass

    passed = failures == 0
    if passed:
        output = "PASS: no module-level Zustand stores"
    else:
        output = "\n".join(messages) + f"\n{failures} Zustand singleton(s) found"

    result = {
        "name": "nextjs-no-zustand-module-level",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

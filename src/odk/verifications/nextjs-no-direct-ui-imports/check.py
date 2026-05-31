#!/usr/bin/env python3
"""Verification plugin: no direct @/components/ui/ imports outside src/shared/ui/."""

import json
import re
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the nextjs-no-direct-ui-imports verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    src_dir = root / "src"

    if not src_dir.is_dir():
        result = {
            "name": "nextjs-no-direct-ui-imports",
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
            # shared/ui/ wrappers ARE allowed to import ShadCN primitives directly
            if "/src/shared/ui/" in fpath or "/components/ui/" in fpath:
                continue

            try:
                for i, line in enumerate(f.read_text().splitlines(), 1):
                    rel = str(f.relative_to(root))
                    if re.search(r"""from ['"]@/components/ui/""", line):
                        messages.append(
                            f"FAIL: {rel}:{i} imports @/components/ui/ directly "
                            "(use @/shared/ui instead):\n  {line.strip()}"
                        )
                        failures += 1
                    elif re.search(r"""from ['"]@/shared/ui/_""", line):
                        messages.append(
                            f"FAIL: {rel}:{i} imports @/shared/ui/_* sub-path "
                            "(use barrel @/shared/ui only):\n  {line.strip()}"
                        )
                        failures += 1
            except OSError:
                pass

    passed = failures == 0
    if passed:
        output = "PASS: no direct @/components/ui/ imports"
    else:
        output = "\n".join(messages) + f"\n{failures} UI import violation(s)"

    result = {
        "name": "nextjs-no-direct-ui-imports",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

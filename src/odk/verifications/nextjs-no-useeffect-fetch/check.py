#!/usr/bin/env python3
"""Verification plugin: no data fetching inside useEffect."""

import json
import re
import sys
import time
from pathlib import Path

FETCH_PATTERN = re.compile(r"fetch\s*\(|\.get\s*\(|\.post\s*\(|getApi[A-Z]|postApi[A-Z]|putApi[A-Z]|deleteApi[A-Z]")


def check_file(filepath: Path) -> list[str]:
    """Check a single file for useEffect fetch patterns using depth tracking."""
    try:
        content = filepath.read_text()
    except OSError:
        return []

    if "useEffect" not in content:
        return []

    violations = []
    lines = content.splitlines()
    in_effect = False
    depth = 0
    effect_line = 0

    for i, line in enumerate(lines, 1):
        if re.search(r"useEffect\s*\(\s*(\(\)|async\s*\(\)|async\s*\(\)\s*=>|function)", line):
            effect_line = i
            in_effect = True
            depth = 0

        if in_effect:
            depth += line.count("{")
            depth -= line.count("}")
            if FETCH_PATTERN.search(line):
                violations.append(f"  {i} (useEffect at {effect_line}): {line.strip()}")
            if depth <= 0:
                in_effect = False

    return violations


def main() -> None:
    """Run the nextjs-no-useeffect-fetch verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    src_dir = root / "src"

    if not src_dir.is_dir():
        result = {
            "name": "nextjs-no-useeffect-fetch",
            "passed": True,
            "output": "PASS: no src/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    failures = 0
    messages: list[str] = []

    for f in src_dir.rglob("*.tsx"):
        if "node_modules" in str(f) or "/generated/" in str(f):
            continue
        violations = check_file(f)
        if violations:
            rel = str(f.relative_to(root))
            messages.append(
                f"FAIL: {rel} fetches data inside useEffect:\n"
                + "\n".join(violations)
                + "\n  Replace with: const {{ data }} = useQuery({{ queryKey: ..., queryFn: ... }})"
            )
            failures += 1

    passed = failures == 0
    if passed:
        output = "PASS: no useEffect data fetching"
    else:
        output = "\n".join(messages) + f"\n{failures} useEffect-fetch pattern(s) found"

    result = {
        "name": "nextjs-no-useeffect-fetch",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

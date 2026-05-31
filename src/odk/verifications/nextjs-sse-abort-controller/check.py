#!/usr/bin/env python3
"""Verification plugin: SSE connections must have cleanup (AbortController or source.close())."""

import json
import re
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the nextjs-sse-abort-controller verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    src_dir = root / "src"

    if not src_dir.is_dir():
        result = {
            "name": "nextjs-sse-abort-controller",
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
            if "node_modules" in str(f) or "/generated/" in str(f):
                continue
            try:
                content = f.read_text()
                if not re.search(r"EventSource|eventsource", content):
                    continue

                # Check that cleanup exists
                has_cleanup = bool(re.search(r"\.close\s*\(\s*\)|\.abort\s*\(\s*\)", content))
                if not has_cleanup:
                    sse_lines = []
                    for i, line in enumerate(content.splitlines(), 1):
                        if re.search(r"new EventSource|EventSource\(", line):
                            sse_lines.append(f"  {i}: {line.strip()}")

                    rel = str(f.relative_to(root))
                    messages.append(
                        f"FAIL: {rel} opens EventSource without cleanup:\n"
                        + "\n".join(sse_lines)
                        + "\n  Add cleanup to the useEffect return:\n"
                        "    return () => source.close()     // for EventSource\n"
                        "    return () => controller.abort() // for fetch-based SSE"
                    )
                    failures += 1
            except OSError:
                pass

    passed = failures == 0
    if passed:
        output = "PASS: all SSE connections have cleanup"
    else:
        output = "\n".join(messages) + f"\n{failures} SSE connection(s) without cleanup"

    result = {
        "name": "nextjs-sse-abort-controller",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

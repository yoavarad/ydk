#!/usr/bin/env python3
"""Guard plugin: block mocking of internal classes.

Only mock at system boundaries (LLM, DB, git, gh). Use fakes for internal classes.
"""

import json
import re
import sys


def main() -> None:
    """Run the guard-no-mock-internals check."""
    try:
        raw = sys.stdin.read()
        context = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        print(
            json.dumps(
                {"name": "guard-no-mock-internals", "passed": True, "output": "PASS: stdin parse failed (fail open)"}
            )
        )
        return
    file_path = context.get("file_path", "")
    content = context.get("new_content", "") or context.get("new_string", "")

    # Only applies to test files
    if not file_path.startswith("tests/"):
        result = {
            "name": "guard-no-mock-internals",
            "passed": True,
            "output": "OK — not a test file",
            "duration_seconds": 0.0,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    # Patterns that indicate mocking internal modules
    internal_patch_patterns = [
        r'@patch\(["\'](?:app|src)\.',
        r'patch\(["\'](?:app|src)\.',
        r"MagicMock\(\s*spec\s*=\s*(?:app|src)\.",
    ]

    for pattern in internal_patch_patterns:
        if re.search(pattern, content):
            result = {
                "name": "guard-no-mock-internals",
                "passed": False,
                "output": (
                    f"BLOCKED: internal mocking detected in {file_path}. "
                    "Mock only at system boundaries (LLM, DB, git, gh). "
                    "Use fakes for internal classes."
                ),
                "duration_seconds": 0.0,
            }
            json.dump(result, sys.stdout)
            sys.exit(1)

    result = {
        "name": "guard-no-mock-internals",
        "passed": True,
        "output": "OK",
        "duration_seconds": 0.0,
    }
    json.dump(result, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Guard plugin: block lint suppressions (noqa, type: ignore, nosec).

Violations must be fixed, not silenced. Exception: tests/ files are
exempt from annotation-rule (ANN*) noqa comments.
"""

import json
import re
import sys


def main() -> None:
    """Run the guard-no-noqa check."""
    try:
        raw = sys.stdin.read()
        context = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        print(json.dumps({"name": "guard-no-noqa", "passed": True, "output": "PASS: stdin parse failed (fail open)"}))
        return
    file_path = context.get("file_path", "")
    content = context.get("new_content", "") or context.get("new_string", "")

    suppression_patterns = [
        (r"#\s*noqa", "# noqa"),
        (r"#\s*type:\s*ignore", "# type: ignore"),
        (r"#\s*nosec", "# nosec"),
    ]

    for pattern, label in suppression_patterns:
        matches = list(re.finditer(pattern, content))
        if not matches:
            continue

        # Exception: ANN* noqa in test files
        if label == "# noqa" and file_path.startswith("tests/"):
            # Check if ALL noqa comments are for ANN rules
            all_ann = True
            for match in matches:
                # Get the line containing this match
                line_start = content.rfind("\n", 0, match.start()) + 1
                line_end = content.find("\n", match.end())
                if line_end == -1:
                    line_end = len(content)
                line = content[line_start:line_end]
                # Check if noqa specifies ANN codes
                noqa_match = re.search(r"#\s*noqa:\s*(ANN\d+(?:\s*,\s*ANN\d+)*)\s*$", line)
                if not noqa_match:
                    all_ann = False
                    break
            if all_ann:
                continue

        result = {
            "name": "guard-no-noqa",
            "passed": False,
            "output": f"BLOCKED: found '{label}' in {file_path}. Fix the violation instead of suppressing it.",
            "duration_seconds": 0.0,
        }
        json.dump(result, sys.stdout)
        sys.exit(1)

    result = {
        "name": "guard-no-noqa",
        "passed": True,
        "output": "OK",
        "duration_seconds": 0.0,
    }
    json.dump(result, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()

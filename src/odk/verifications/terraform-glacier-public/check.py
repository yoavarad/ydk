#!/usr/bin/env python3
"""Verification plugin: detect Glacier vault public access."""

import json
import re
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the terraform-glacier-public verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    messages: list[str] = []
    root = Path(project_root)

    for tf in root.rglob("*.tf"):
        try:
            content = tf.read_text()
            lines = content.splitlines()
            in_glacier = False
            glacier_start = 0
            for i, line in enumerate(lines):
                if "aws_glacier_vault" in line:
                    in_glacier = True
                    glacier_start = i
                if (
                    in_glacier
                    and i <= glacier_start + 20
                    and re.search(r"(access_policy|Principal)", line)
                    and "*" in line
                ):
                    messages.append(f"{tf}:{i + 1}: {line.strip()}")
                if in_glacier and i > glacier_start + 20:
                    in_glacier = False
        except OSError:
            pass

    passed = len(messages) == 0
    if passed:
        output = "PASS: No public Glacier vault access detected."
    else:
        output = (
            "FAIL: Found Glacier vault with public access policy:\n"
            + "\n".join(messages)
            + "\n\nRestrict Glacier vault access_policy principals to specific accounts/roles."
        )

    result = {
        "name": "terraform-glacier-public",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": None,
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

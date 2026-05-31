#!/usr/bin/env python3
"""Verification plugin: detect wildcard IAM principals."""

import json
import re
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the terraform-external-iam verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    messages: list[str] = []
    root = Path(project_root)

    for tf in root.rglob("*.tf"):
        try:
            for i, line in enumerate(tf.read_text().splitlines(), 1):
                if re.search(r"Principal.*\*", line) and re.search(r"(assume_role_policy|Principal)", line):
                    messages.append(f"{tf}:{i}: {line.strip()}")
        except OSError:
            pass

    passed = len(messages) == 0
    if passed:
        output = "PASS: No wildcard IAM principals found."
    else:
        output = (
            "FAIL: Found wildcard IAM principals:\n"
            + "\n".join(messages)
            + '\n\nWildcard principals ("*") allow any entity to assume a role or access a resource.\n'
            "Restrict principals to specific AWS accounts, services, or ARNs."
        )

    result = {
        "name": "terraform-external-iam",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": None,
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

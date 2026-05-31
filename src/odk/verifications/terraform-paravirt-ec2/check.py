#!/usr/bin/env python3
"""Verification plugin: detect paravirtualized EC2 instance types."""

import json
import re
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the terraform-paravirt-ec2 verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    messages: list[str] = []
    root = Path(project_root)

    for tf in root.rglob("*.tf"):
        try:
            for i, line in enumerate(tf.read_text().splitlines(), 1):
                if re.search(r'instance_type.*=.*"(t1\.|m1\.|c1\.|m2\.)', line):
                    messages.append(f"{tf}:{i}: {line.strip()}")
        except OSError:
            pass

    passed = len(messages) == 0
    if passed:
        output = "PASS: No paravirtualized instance types found."
    else:
        output = (
            "FAIL: Found paravirtualized EC2 instance types:\n"
            + "\n".join(messages)
            + "\n\nThese instance types use paravirtualization and lack modern security features.\n"
            "Use HVM-based instance types (t3.*, m5.*, c5.*, etc.) instead."
        )

    result = {
        "name": "terraform-paravirt-ec2",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": None,
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

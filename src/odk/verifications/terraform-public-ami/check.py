#!/usr/bin/env python3
"""Verification plugin: detect AMI usage without owner restrictions."""

import contextlib
import json
import re
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the terraform-public-ami verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    errors = 0
    messages: list[str] = []
    root = Path(project_root)

    tf_files = list(root.rglob("*.tf"))
    all_text = ""
    for tf in tf_files:
        with contextlib.suppress(OSError):
            all_text += tf.read_text() + "\n"

    # Check for hardcoded AMI IDs without data source lookups
    has_ami_refs = bool(re.search(r"ami-[0-9a-f]{8,17}", all_text))
    has_data_ami = bool(re.search(r'data "aws_ami"', all_text))

    if has_ami_refs and not has_data_ami:
        messages.append(
            "WARN: Found hardcoded AMI IDs without data source lookups.\n"
            '  Consider using data "aws_ami" with owners = ["amazon", "self"] for verified images.'
        )

    # Check data "aws_ami" blocks without owners
    for tf in tf_files:
        try:
            content = tf.read_text()
            if 'data "aws_ami"' in content and "owners" not in content:
                messages.append(
                    f'FAIL: {tf} has data "aws_ami" without owners restriction.\n'
                    '  Add: owners = ["amazon", "self"] to restrict to trusted AMI sources.'
                )
                errors += 1
        except OSError:
            pass

    passed = errors == 0
    if passed:
        output = "PASS: AMI usage checks passed."
        if messages:
            output = "\n".join(messages) + "\n" + output
    else:
        output = "\n".join(messages) + f"\nFAIL: {errors} AMI source(s) missing owner restrictions."

    result = {
        "name": "terraform-public-ami",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"errors": errors},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Verification plugin: detect dangling Route53 and CloudFront origins."""

import contextlib
import json
import re
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the terraform-dangling-resources verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    errors = 0
    messages: list[str] = []

    root = Path(project_root)
    tf_files = list(root.rglob("*.tf"))

    # Read all tf content for searching
    tf_contents: dict[str, str] = {}
    for tf in tf_files:
        with contextlib.suppress(OSError):
            tf_contents[str(tf)] = tf.read_text()

    all_tf_text = "\n".join(tf_contents.values())

    # Check for Route53 alias records pointing to S3 buckets not defined in code
    alias_lines = []
    for content in tf_contents.values():
        for i, line in enumerate(content.splitlines(), 1):
            if "alias" in line.lower():
                # Grab surrounding context (next 5 lines)
                lines = content.splitlines()
                ctx = "\n".join(lines[i - 1 : i + 5])
                if re.search(r"s3", ctx, re.IGNORECASE):
                    alias_lines.append(ctx)

    for ctx in alias_lines:
        bucket_domains = re.findall(r"[a-z0-9][a-z0-9.\-]*\.s3[a-z0-9.\-]*\.amazonaws\.com", ctx)
        for bucket_domain in bucket_domains:
            bucket_name = bucket_domain.split(".s3")[0]
            pattern1 = f'bucket.*=.*"{bucket_name}"'
            pattern2 = f'resource "aws_s3_bucket" "{bucket_name}"'
            if not re.search(pattern1, all_tf_text) and not re.search(pattern2, all_tf_text):
                messages.append(
                    f"WARN: Route53 alias points to S3 bucket '{bucket_name}' which may not be defined in code."
                )
                errors += 1

    # Check for CloudFront origins with hardcoded AWS domains
    for content in tf_contents.values():
        lines = content.splitlines()
        in_origin = False
        for _i, line in enumerate(lines):
            if "origin" in line and "{" in line:
                in_origin = True
            if (
                in_origin
                and "domain_name" in line
                and re.search(r'"[^"]*\.(s3|elb|execute-api)[^"]*\.amazonaws\.com"', line)
            ):
                messages.append(
                    f"WARN: CloudFront origin with hardcoded AWS domain: {line.strip()}\n"
                    "  Use resource references instead."
                )
                errors += 1
            if in_origin and "}" in line:
                in_origin = False

    passed = errors == 0
    if passed:
        output = "PASS: No dangling resource references detected."
    else:
        output = "\n".join(messages) + f"\nFAIL: {errors} potential dangling resource reference(s) found."

    result = {
        "name": "terraform-dangling-resources",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"errors": errors},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

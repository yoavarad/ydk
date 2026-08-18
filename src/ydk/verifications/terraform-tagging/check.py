#!/usr/bin/env python3
"""Verification plugin: check that all Terraform resources have required tags."""

import json
import re
import sys
import time
from pathlib import Path

SKIP_RESOURCE_TYPES = {
    "aws_iam_role_policy_attachment",
    "aws_route_table_association",
    "aws_s3_bucket_policy",
    "aws_s3_bucket_versioning",
    "aws_s3_bucket_server_side_encryption",
    "aws_s3_bucket_public_access_block",
}


def main() -> None:
    """Run the terraform-tagging verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    infra_dir = Path(project_root) / "infra"

    if not infra_dir.is_dir():
        result = {
            "name": "terraform-tagging",
            "passed": True,
            "output": "SKIP: No infra/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    warnings: list[str] = []

    for tf_file in sorted(infra_dir.glob("*.tf")):
        try:
            content = tf_file.read_text()
        except OSError:
            continue

        lines = content.splitlines()
        for i, line in enumerate(lines):
            match = re.match(r'^resource "([^"]+)"', line)
            if not match:
                continue

            resource_type = match.group(1)
            if resource_type in SKIP_RESOURCE_TYPES:
                continue

            # Look for tags block within the next 100 lines
            block = "\n".join(lines[i : i + 100])
            if "tags = {" not in block:
                warnings.append(f"WARN: {tf_file}:{i + 1} - {line.strip()} may be missing tags")

    # Original script uses warnings but never increments ERRORS, so always passes
    passed = True
    output_parts = [*warnings, "PASS: Tagging checks passed."]
    output = "\n".join(output_parts)

    result = {
        "name": "terraform-tagging",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"warnings": len(warnings)},
    }
    json.dump(result, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()

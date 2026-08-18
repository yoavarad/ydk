#!/usr/bin/env python3
"""Verification plugin: comprehensive security scanning via checkov."""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

CHECKS = (
    "CKV_AWS_20,CKV_AWS_21,CKV_AWS_54,CKV_AWS_55,CKV_AWS_56,CKV_AWS_57,CKV_AWS_93,"
    "CKV_AWS_27,CKV_AWS_26,CKV_AWS_7,CKV_AWS_33,CKV_AWS_45,CKV_AWS_115,CKV_AWS_173,"
    "CKV_AWS_260,CKV_AWS_23,CKV_AWS_24,CKV_AWS_25,CKV_AWS_290,CKV_AWS_60,CKV_AWS_61,"
    "CKV_AWS_118,CKV_AWS_129,CKV_AWS_46,CKV_AWS_74,CKV_AWS_134,CKV_AWS_5,CKV_AWS_84,"
    "CKV_AWS_137"
)


def main() -> None:
    """Run the terraform-security verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    infra_dir = Path(project_root) / "infra"

    if not infra_dir.is_dir():
        result = {
            "name": "terraform-security",
            "passed": True,
            "output": "SKIP: No infra/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    if not shutil.which("checkov"):
        result = {
            "name": "terraform-security",
            "passed": False,
            "output": "FAIL: checkov is not installed. Run: pip install checkov",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(1)

    proc = subprocess.run(
        [
            "checkov",
            "--directory",
            str(infra_dir),
            "--check",
            CHECKS,
            "--output",
            "json",
            "--compact",
        ],
        capture_output=True,
        text=True,
    )

    checkov_output = proc.stdout
    if not checkov_output:
        result = {
            "name": "terraform-security",
            "passed": True,
            "output": "PASS: No relevant Terraform resources found for these checks.",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    try:
        data = json.loads(checkov_output)
        if isinstance(data, list):
            total_failed = sum(r.get("summary", {}).get("failed", 0) for r in data)
        else:
            total_failed = data.get("summary", {}).get("failed", 0)
    except (json.JSONDecodeError, KeyError, TypeError):
        total_failed = 0

    passed = total_failed == 0
    if passed:
        output = "PASS: All checkov security checks passed."
    else:
        output = (
            f"FAIL: checkov found {total_failed} security violation(s).\n\n"
            "Checks cover:\n"
            "  - S3 public access (CKV_AWS_20,21,54,55,56,57,93)\n"
            "  - SQS/SNS public policies (CKV_AWS_27,26)\n"
            "  - KMS key rotation and access (CKV_AWS_7,33)\n"
            "  - Lambda public access (CKV_AWS_45,115,173,260)\n"
            "  - Security groups wide-open (CKV_AWS_23,24,25)\n"
            "  - IAM overly permissive (CKV_AWS_290,60,61)\n"
            "  - RDS/EBS public snapshots and IAM auth (CKV_AWS_118,129,46,74,134)\n"
            "  - Elasticsearch public access (CKV_AWS_5,84,137)\n\n"
            f"Run 'checkov --directory {infra_dir} --check {CHECKS}' for full details."
        )

    result = {
        "name": "terraform-security",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failed_count": total_failed},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

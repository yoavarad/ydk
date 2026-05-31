#!/usr/bin/env python3
"""Verification plugin: check Terraform formatting."""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    """Run the terraform-format verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    infra_dir = Path(project_root) / "infra"

    if not infra_dir.is_dir():
        result = {
            "name": "terraform-format",
            "passed": True,
            "output": "SKIP: No infra/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    if not shutil.which("terraform"):
        result = {
            "name": "terraform-format",
            "passed": True,
            "output": "WARN: terraform not installed, skipping format check",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    proc = subprocess.run(
        ["terraform", "fmt", "-check", "-recursive", "-diff", str(infra_dir)],
        capture_output=True,
        text=True,
    )

    unformatted = proc.stdout.strip()
    passed = not unformatted
    if passed:
        output = "PASS: All .tf files are properly formatted."
    else:
        output = (
            "FAIL: The following files are not properly formatted:\n"
            + unformatted
            + "\n\nRun 'terraform fmt -recursive infra/' to fix."
        )

    result = {
        "name": "terraform-format",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": None,
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

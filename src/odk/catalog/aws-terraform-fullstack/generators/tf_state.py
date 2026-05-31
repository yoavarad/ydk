#!/usr/bin/env python3
"""
Generator: tf-state
Generates S3 backend configuration and DynamoDB lock table + bootstrap script.
Input: infrastructure.yaml
Output: state.tf, bootstrap.sh
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _context.loader import common_tags, load_artifact, render_and_write


def main() -> None:
    """Generate Terraform state backend configuration."""
    infra = load_artifact("infrastructure")
    app = infra.get("app", {})
    tags = common_tags(infra)

    context = {
        "app_name": app.get("name", "app"),
        "environment": app.get("environment", "dev"),
        "region": app.get("region", "us-east-1"),
        "tags": tags,
    }

    render_and_write("state.tf.j2", "state.tf", context)
    render_and_write("bootstrap.sh.j2", "bootstrap.sh", context)


if __name__ == "__main__":
    main()

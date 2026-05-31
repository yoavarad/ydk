#!/usr/bin/env python3
"""
Generator: tf-variables
Generates variables.tf and terraform.tfvars.
Input: infrastructure.yaml
Output: variables.tf, terraform.tfvars
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _context.loader import common_tags, load_artifact, render_and_write


def main() -> None:
    """Generate variables.tf and terraform.tfvars."""
    infra = load_artifact("infrastructure")
    app = infra.get("app", {})
    compute = infra.get("compute", {})
    database = infra.get("database", {})
    networking = infra.get("networking", {})
    auth = infra.get("auth", {})
    tags = common_tags(infra)

    context = {
        "app_name": app.get("name", "app"),
        "environment": app.get("environment", "dev"),
        "region": app.get("region", "us-east-1"),
        "domain": app.get("domain", ""),
        "cpu": compute.get("cpu", 512),
        "memory": compute.get("memory", 1024),
        "container_port": compute.get("port", 8000),
        "desired_count": compute.get("desired_count", 2),
        "engine_version": database.get("engine_version", "15.4"),
        "min_acu": database.get("min_acu", 0.5),
        "max_acu": database.get("max_acu", 4),
        "vpc_cidr": networking.get("vpc_cidr", "10.0.0.0/16"),
        "nat_gateway_mode": networking.get("nat_gateway_mode", "single"),
        "auth_provider": auth.get("provider", "none"),
        "tags": tags,
    }

    render_and_write("variables.tf.j2", "variables.tf", context)
    render_and_write("terraform.tfvars.j2", "terraform.tfvars", context)


if __name__ == "__main__":
    main()

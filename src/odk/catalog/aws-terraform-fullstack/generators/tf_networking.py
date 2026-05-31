#!/usr/bin/env python3
"""
Generator: tf-networking
Generates VPC, subnets, NAT gateway, security groups.
Input: infrastructure.yaml
Output: networking.tf
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _context.loader import common_tags, load_artifact, render_and_write


def main() -> None:
    """Generate VPC, subnets, NAT gateway, security groups."""
    infra = load_artifact("infrastructure")
    app = infra.get("app", {})
    networking = infra.get("networking", {})
    compute = infra.get("compute", {})
    tags = common_tags(infra)

    context = {
        "app_name": app.get("name", "app"),
        "environment": app.get("environment", "dev"),
        "region": app.get("region", "us-east-1"),
        "vpc_cidr": networking.get("vpc_cidr", "10.0.0.0/16"),
        "nat_gateway_mode": networking.get("nat_gateway_mode", "single"),
        "availability_zones": networking.get("availability_zones", 2),
        "container_port": compute.get("port", 8000),
        "tags": tags,
    }

    render_and_write("networking.tf.j2", "networking.tf", context)


if __name__ == "__main__":
    main()

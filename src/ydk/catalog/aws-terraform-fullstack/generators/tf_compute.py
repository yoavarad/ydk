#!/usr/bin/env python3
"""
Generator: tf-compute
Generates ECS Fargate task definitions, service, ALB, ECR, IAM roles.
Input: infrastructure.yaml
Output: compute.tf
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _context.loader import common_tags, load_artifact, render_and_write


def main() -> None:
    """Generate ECS Fargate task definitions, service, ALB."""
    infra = load_artifact("infrastructure")
    app = infra.get("app", {})
    compute = infra.get("compute", {})
    monitoring = infra.get("monitoring", {})
    tags = common_tags(infra)

    autoscaling = compute.get("autoscaling", {})

    context = {
        "app_name": app.get("name", "app"),
        "environment": app.get("environment", "dev"),
        "region": app.get("region", "us-east-1"),
        "cpu": compute.get("cpu", 512),
        "memory": compute.get("memory", 1024),
        "container_port": compute.get("port", 8000),
        "desired_count": compute.get("desired_count", 2),
        "health_check_path": compute.get("health_check_path", "/health"),
        "min_count": autoscaling.get("min_count", 1),
        "max_count": autoscaling.get("max_count", 4),
        "cpu_threshold": autoscaling.get("cpu_threshold", 70),
        "log_retention_days": monitoring.get("log_retention_days", 30),
        "tags": tags,
    }

    render_and_write("compute.tf.j2", "compute.tf", context)


if __name__ == "__main__":
    main()

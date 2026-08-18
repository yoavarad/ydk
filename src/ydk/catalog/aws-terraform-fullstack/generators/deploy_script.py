#!/usr/bin/env python3
"""
Generator: deploy-script
Generates deploy.sh with terraform plan/apply + docker build/push + cache invalidation.
Input: infrastructure.yaml
Output: deploy.sh
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _context.loader import load_artifact, render_and_write


def main() -> None:
    """Generate deploy.sh with terraform and docker commands."""
    infra = load_artifact("infrastructure")
    app = infra.get("app", {})
    cdn = infra.get("cdn", {})

    context = {
        "app_name": app.get("name", "app"),
        "environment": app.get("environment", "dev"),
        "region": app.get("region", "us-east-1"),
        "has_cdn": cdn.get("enabled", True),
    }

    render_and_write("deploy.sh.j2", "deploy.sh", context)


if __name__ == "__main__":
    main()

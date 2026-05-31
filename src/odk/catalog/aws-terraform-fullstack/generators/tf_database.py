#!/usr/bin/env python3
"""
Generator: tf-database
Generates Aurora Serverless v2 cluster configuration.
Input: infrastructure.yaml
Output: database.tf
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _context.loader import common_tags, load_artifact, render_and_write


def main() -> None:
    """Generate Aurora Serverless v2 cluster configuration."""
    infra = load_artifact("infrastructure")
    app = infra.get("app", {})
    database = infra.get("database", {})
    tags = common_tags(infra)

    context = {
        "app_name": app.get("name", "app"),
        "environment": app.get("environment", "dev"),
        "engine_version": database.get("engine_version", "15.4"),
        "min_acu": database.get("min_acu", 0.5),
        "max_acu": database.get("max_acu", 4),
        "backup_retention_days": database.get("backup_retention_days", 7),
        "deletion_protection": database.get("deletion_protection", False),
        "tags": tags,
    }

    render_and_write("database.tf.j2", "database.tf", context)


if __name__ == "__main__":
    main()

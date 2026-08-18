#!/usr/bin/env python3
"""
Generator: tf-cdn
Generates CloudFront distribution + S3 bucket for frontend.
Input: infrastructure.yaml
Output: cdn.tf
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _context.loader import common_tags, load_artifact, render_and_write


def main() -> None:
    """Generate CloudFront distribution and S3 frontend bucket."""
    infra = load_artifact("infrastructure")
    app = infra.get("app", {})
    cdn = infra.get("cdn", {})
    tags = common_tags(infra)

    if not cdn.get("enabled", True):
        # Write empty file with comment
        from _context.loader import write_output

        write_output("cdn.tf", "# CDN disabled in infrastructure.yaml\n")
        return

    custom_error_responses = cdn.get("custom_error_responses", [])

    context = {
        "app_name": app.get("name", "app"),
        "environment": app.get("environment", "dev"),
        "domain": app.get("domain", ""),
        "price_class": cdn.get("price_class", "PriceClass_100"),
        "api_path_pattern": cdn.get("api_path_pattern", "/api/*"),
        "custom_error_responses": custom_error_responses,
        "tags": tags,
    }

    render_and_write("cdn.tf.j2", "cdn.tf", context)


if __name__ == "__main__":
    main()

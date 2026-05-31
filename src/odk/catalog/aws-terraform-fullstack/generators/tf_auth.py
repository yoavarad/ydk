#!/usr/bin/env python3
"""
Generator: tf-auth
Generates Cognito user pool configuration (conditional).
Input: infrastructure.yaml
Output: auth.tf (empty if auth not configured)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _context.loader import common_tags, load_artifact, render_and_write, write_output


def main() -> None:
    """Generate Cognito user pool configuration."""
    infra = load_artifact("infrastructure")
    app = infra.get("app", {})
    auth = infra.get("auth", {})
    tags = common_tags(infra)

    provider = auth.get("provider", "none")
    if provider != "cognito":
        write_output("auth.tf", "# Authentication not configured (auth.provider != cognito)\n")
        return

    password_policy = auth.get("password_policy", {})

    context = {
        "app_name": app.get("name", "app"),
        "environment": app.get("environment", "dev"),
        "minimum_length": password_policy.get("minimum_length", 8),
        "require_uppercase": password_policy.get("require_uppercase", True),
        "require_lowercase": password_policy.get("require_lowercase", True),
        "require_numbers": password_policy.get("require_numbers", True),
        "require_symbols": password_policy.get("require_symbols", False),
        "mfa": auth.get("mfa", "off"),
        "tags": tags,
    }

    render_and_write("auth.tf.j2", "auth.tf", context)


if __name__ == "__main__":
    main()

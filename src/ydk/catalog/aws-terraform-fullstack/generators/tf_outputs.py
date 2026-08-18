#!/usr/bin/env python3
"""
Generator: tf-outputs
Generates outputs.tf with key infrastructure outputs.
Input: infrastructure.yaml
Output: outputs.tf
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _context.loader import load_artifact, render_and_write


def main() -> None:
    """Generate outputs.tf with key infrastructure outputs."""
    infra = load_artifact("infrastructure")
    app = infra.get("app", {})
    auth = infra.get("auth", {})
    cdn = infra.get("cdn", {})

    context = {
        "app_name": app.get("name", "app"),
        "has_auth": auth.get("provider", "none") == "cognito",
        "has_cdn": cdn.get("enabled", True),
    }

    render_and_write("outputs.tf.j2", "outputs.tf", context)


if __name__ == "__main__":
    main()

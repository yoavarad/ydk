#!/usr/bin/env python3
"""
Generator: openapi-sdk
Generates typed TypeScript SDK from OpenAPI spec using @hey-api/openapi-ts.

Input:  ODK_ARTIFACT_OPENAPI (path to openapi.json)
Output: src/shared/api/generated/ (written by bunx, then read back into ODK protocol)

Deferred-safe: if no openapi.json is available, prints a warning and returns [].
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _resolve_openapi_input(env: dict[str, str], project_root: Path) -> str | None:
    """
    Resolve the OpenAPI input source with correct priority:
      1. ODK_ARTIFACT_OPENAPI — artifact path from prior phase
      2. Adjacent backend dist file
      3. None — defer

    Returns None only when no local file is reachable and we should defer.
    """
    artifact = env.get("ODK_ARTIFACT_OPENAPI", "")
    if artifact and Path(artifact).exists():
        return artifact

    adjacent = project_root.parent / "backend" / "dist" / "openapi.json"
    if adjacent.exists():
        return str(adjacent)

    # No local file — defer
    return None


def _collect_output(output_dir: Path) -> list[dict]:
    """Read generated .ts files and return as ODK generator protocol [{path, content}]."""
    if not output_dir.exists():
        return []
    return [{"path": f.name, "content": f.read_text(encoding="utf-8")} for f in sorted(output_dir.glob("*.ts"))]


def main() -> None:
    project_root_str = os.environ.get("ODK_PROJECT_ROOT", "")
    if not project_root_str:
        print("Error: ODK_PROJECT_ROOT is not set", file=sys.stderr)
        sys.exit(1)

    project_root = Path(project_root_str)
    output_dir = Path(os.environ.get("ODK_OUTPUT_DIR", str(project_root / "src/shared/api/generated")))
    output_dir.mkdir(parents=True, exist_ok=True)

    openapi_input = _resolve_openapi_input(dict(os.environ), project_root)
    if openapi_input is None:
        print(
            "Warning: no openapi.json found and ODK_ARTIFACT_OPENAPI not set — SDK generation deferred.",
            file=sys.stderr,
        )
        print(json.dumps([]))
        return

    print(f"Generating SDK from: {openapi_input}", file=sys.stderr)

    result = subprocess.run(
        [
            "bunx",
            "@hey-api/openapi-ts",
            "--input",
            openapi_input,
            "--output",
            str(output_dir),
            "--client",
            "@hey-api/client-axios",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"Error running @hey-api/openapi-ts:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(_collect_output(output_dir)))


if __name__ == "__main__":
    main()

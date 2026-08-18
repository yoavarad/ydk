#!/usr/bin/env python3
"""
Generator: openapi-spec-export
Exports the FastAPI app's OpenAPI spec to dist/openapi.json.
No database connection needed — only introspects route definitions.
Run this before running the frontend nextjs-openapi-sdk generator.

If the project has its own .venv, the export runs in a subprocess using
the project's Python so that fastapi/pydantic/etc. are importable.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

output_dir = Path(os.environ["YDK_OUTPUT_DIR"])
output_dir.mkdir(parents=True, exist_ok=True)
project_root = os.environ["YDK_PROJECT_ROOT"]

# Dummy env vars so pydantic-settings loads without a real DB
_env_defaults = {
    "DATABASE_URL": "postgresql+asyncpg://localhost/schema_export_dummy",
    "COGNITO_REGION": "us-east-1",
    "COGNITO_USER_POOL_ID": "dummy",
    "COGNITO_CLIENT_ID": "dummy",
}

venv_python = Path(project_root) / ".venv" / "bin" / "python3"

if venv_python.exists():
    # Run in the project's venv so that fastapi, pydantic, etc. are available
    export_script = (
        "import sys, json; "
        "sys.path.insert(0, '.'); "
        "from app.main import create_app; "
        "print(json.dumps(create_app().openapi()))"
    )
    env = {**os.environ, **{k: os.environ.get(k, v) for k, v in _env_defaults.items()}}
    result = subprocess.run(
        [str(venv_python), "-c", export_script],
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )
    if result.returncode != 0:
        # Check if this is an ImportError (expected during initial generation)
        if (
            "ImportError" in result.stderr
            or "ModuleNotFoundError" in result.stderr
            or "No module named" in result.stderr
        ):
            print(
                "Warning: cannot export OpenAPI spec — backend not yet installed.\n"
                "This is expected during initial `ydk ignite`. Run 'uv sync' then:\n"
                "  ydk ignite --id openapi-spec-export",
                file=sys.stderr,
            )
            print(json.dumps([]))  # empty output — deferred
            sys.exit(0)
        print(
            f"Error exporting OpenAPI spec via project venv:\n{result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)
    spec = json.loads(result.stdout)
else:
    # Fallback: try importing directly (works when ydk runs inside the project venv)
    sys.path.insert(0, project_root)
    for k, v in _env_defaults.items():
        os.environ.setdefault(k, v)
    try:
        from app.main import create_app

        spec = create_app().openapi()
    except ImportError as e:
        # Expected during initial generation — uv sync not yet run.
        print(
            f"Warning: cannot export OpenAPI spec — backend not yet installed ({e}).\n"
            "This is expected during initial `ydk ignite`. Run 'uv sync' then:\n"
            "  ydk ignite --id openapi-spec-export",
            file=sys.stderr,
        )
        print(json.dumps([]))  # empty output — deferred
        sys.exit(0)
    except Exception as e:
        print(f"Error exporting OpenAPI spec: {e}", file=sys.stderr)
        sys.exit(1)

spec_json = json.dumps(spec, indent=2)
output_path = output_dir / "openapi.json"
output_path.write_text(spec_json)
print(json.dumps([{"path": "openapi.json", "content": spec_json}]))

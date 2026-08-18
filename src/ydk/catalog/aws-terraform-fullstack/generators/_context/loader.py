"""Shared artifact loading and template rendering utilities.

YDK adapter shim: translates YDK_* env vars to the loader interface expected
by infrastructure generators, and emits JSON to stdout for the YDK ignition
engine.

This shim intercepts writes, buffers them, and flushes JSON on process exit.
"""

from __future__ import annotations

import atexit
import json
import os
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

# ---------------------------------------------------------------------------
# Internal buffer — collects generated files for JSON output
# ---------------------------------------------------------------------------
_generated_files: list[dict[str, str]] = []


def _flush_json() -> None:
    """Emit buffered files as JSON array to stdout (YDK protocol)."""
    if _generated_files:
        print(json.dumps(_generated_files))


atexit.register(_flush_json)


# ---------------------------------------------------------------------------
# Artifact loading — reads from YDK component YAML
# ---------------------------------------------------------------------------
def load_artifact(artifact_name: str = "infrastructure") -> dict:
    """Load artifact data from YDK components.

    Resolution order:
      1. YDK_COMPONENTS_INFRASTRUCTURE env var (YDK ignition engine path)
    """
    # YDK path: components are passed as YAML list; infrastructure pack
    # expects a single dict, so we merge the list into one dict.
    ydk_key = f"YDK_COMPONENTS_{artifact_name.upper().replace('-', '_')}"
    ydk_path = os.environ.get(ydk_key)
    if ydk_path and Path(ydk_path).exists():
        raw = yaml.safe_load(Path(ydk_path).read_text())
        if isinstance(raw, list):
            merged: dict = {}
            for item in raw:
                if isinstance(item, dict):
                    merged.update(item)
            return merged
        if isinstance(raw, dict):
            return raw

    print(f"ERROR: Component data not found: {ydk_key}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------
def get_template_env() -> Environment:
    """Get Jinja2 environment pointing to the templates directory."""
    templates_dir = Path(__file__).parent.parent.parent / "templates"
    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def get_output_dir() -> Path:
    """Get the output directory from YDK_OUTPUT_DIR."""
    output_dir = Path(os.environ.get("YDK_OUTPUT_DIR", "."))
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def write_output(filename: str, content: str) -> None:
    """Buffer generated content for JSON output (YDK protocol)."""
    output_dir = get_output_dir()
    rel_path = str(Path(output_dir.name) / filename) if output_dir.name != "." else filename
    _generated_files.append({"path": rel_path, "content": content})


def render_and_write(template_name: str, output_filename: str, context: dict) -> None:
    """Load a Jinja2 template, render it, and buffer for output."""
    env = get_template_env()
    template = env.get_template(template_name)
    content = template.render(**context)
    write_output(output_filename, content)


def common_tags(infra: dict) -> dict:
    """Build common tags dict from infrastructure config."""
    app = infra.get("app", {})
    return {
        "Environment": app.get("environment", "dev"),
        "Project": app.get("name", "app"),
        "ManagedBy": "terraform",
    }

#!/usr/bin/env python3
"""Generator: cli-pyproject (ODK ignition pack).

Generates pyproject.toml with all dependencies.
Input: contract component (cli-commands data)
Output: JSON array of generated files to stdout (ODK protocol).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _odk_adapter import emit, load_commands_from_odk_components
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def generate(data: dict) -> list[dict[str, str]]:
    """Generate pyproject.toml."""
    template_dir = Path(__file__).parent.parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )

    template = env.get_template("pyproject.toml.j2")
    content = template.render(
        app_name=data.get("app_name", "cli"),
    )
    return [{"path": "pyproject.toml", "content": content}]


def main() -> None:
    """Entry point: load ODK components and generate pyproject.toml."""
    data = load_commands_from_odk_components()
    if not data:
        emit([])
        return
    emit(generate(data))


if __name__ == "__main__":
    main()

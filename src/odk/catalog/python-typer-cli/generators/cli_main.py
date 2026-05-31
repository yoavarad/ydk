#!/usr/bin/env python3
"""Generator: cli-main (ODK ignition pack).

Generates the Typer app entry point with group registration.
Input: contract component (cli-commands data)
Output: JSON array of generated files to stdout (ODK protocol).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _context.naming import to_snake
from _odk_adapter import emit, load_commands_from_odk_components
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def generate(data: dict) -> list[dict[str, str]]:
    """Generate the main entry point files."""
    template_dir = Path(__file__).parent.parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    env.filters["to_snake"] = to_snake

    files: list[dict[str, str]] = []

    # __init__.py
    app_name = data.get("app_name", "cli")
    files.append(
        {
            "path": "src/__init__.py",
            "content": f'"""{app_name} CLI package."""\n',
        }
    )

    # main.py
    template = env.get_template("main.py.j2")
    content = template.render(
        app_name=app_name,
        groups=data.get("groups", []),
    )
    files.append({"path": "src/main.py", "content": content})

    return files


def main() -> None:
    """Entry point: load ODK components and generate main entry point."""
    data = load_commands_from_odk_components()
    if not data:
        emit([])
        return
    emit(generate(data))


if __name__ == "__main__":
    main()

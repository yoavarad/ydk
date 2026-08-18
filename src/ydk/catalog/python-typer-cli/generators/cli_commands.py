#!/usr/bin/env python3
"""Generator: cli-commands (YDK ignition pack).

Generates per-group command files with Typer commands.
Input: contract component (cli-commands data)
Output: JSON array of generated files to stdout (YDK protocol).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _context.naming import to_snake
from _context.types import python_type, typer_default
from _ydk_adapter import emit, load_commands_from_ydk_components
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def generate(data: dict) -> list[dict[str, str]]:
    """Generate command group files."""
    template_dir = Path(__file__).parent.parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    env.filters["to_snake"] = to_snake
    env.filters["python_type"] = python_type
    env.filters["typer_default"] = lambda val, typ: typer_default(val, typ)

    files: list[dict[str, str]] = []

    # __init__.py
    files.append(
        {
            "path": "src/commands/__init__.py",
            "content": '"""CLI command groups."""\n',
        }
    )

    # One file per group
    template = env.get_template("command_group.py.j2")
    for group in data.get("groups", []):
        content = template.render(
            group=group,
            app_name=data.get("app_name", "cli"),
            base_url_env=data.get("base_url_env", "CLI_BASE_URL"),
        )
        files.append(
            {
                "path": f"src/commands/{to_snake(group['name'])}.py",
                "content": content,
            }
        )

    return files


def main() -> None:
    """Entry point: load YDK components and generate command files."""
    data = load_commands_from_ydk_components()
    if not data:
        emit([])
        return
    emit(generate(data))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generator: cli-tests (ODK ignition pack).

Generates test files using CliRunner and respx for HTTP mocking.
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

_CONFTEST_CONTENT = (
    '"""Shared test fixtures."""\n\n'
    "import pytest\n"
    "from typer.testing import CliRunner\n\n"
    "from src.main import app\n\n\n"
    "@pytest.fixture\n"
    "def runner():\n"
    '    """Create a CliRunner instance."""\n'
    "    return CliRunner()\n\n\n"
    "@pytest.fixture\n"
    "def cli_app():\n"
    '    """Return the Typer app."""\n'
    "    return app\n"
)


def generate(data: dict) -> list[dict[str, str]]:
    """Generate test files."""
    template_dir = Path(__file__).parent.parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    env.filters["to_snake"] = to_snake

    files: list[dict[str, str]] = []

    # conftest.py
    files.append({"path": "tests/conftest.py", "content": _CONFTEST_CONTENT})

    # Test file per group
    template = env.get_template("test_commands.py.j2")
    for group in data.get("groups", []):
        content = template.render(
            group=group,
            app_name=data.get("app_name", "cli"),
            base_url_env=data.get("base_url_env", "CLI_BASE_URL"),
        )
        files.append(
            {
                "path": f"tests/test_{to_snake(group['name'])}.py",
                "content": content,
            }
        )

    return files


def main() -> None:
    """Entry point: load ODK components and generate test files."""
    data = load_commands_from_odk_components()
    if not data:
        emit([])
        return
    emit(generate(data))


if __name__ == "__main__":
    main()

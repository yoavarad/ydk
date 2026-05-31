#!/usr/bin/env python3
"""Generator: cli-client (ODK ignition pack).

Generates the httpx-based HTTP client with auth and error handling.
Input: contract component (cli-commands data)
Output: JSON array of generated files to stdout (ODK protocol).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add generators dir to path for _context imports
sys.path.insert(0, str(Path(__file__).parent))

from _context.naming import to_snake
from _odk_adapter import emit, load_commands_from_odk_components
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def _generate_auth(auth_config: dict) -> str:
    """Generate auth module content."""
    lines = [
        '"""Authentication handling for the HTTP client."""',
        "",
        "from __future__ import annotations",
        "",
        "import os",
        "",
        "import httpx",
        "",
        "",
    ]

    auth_type = auth_config.get("type", "none")

    if auth_type == "api_key":
        header = auth_config.get("header", "X-API-Key")
        env_var = auth_config.get("env_var", "API_KEY")
        lines.extend(
            [
                "def apply_auth(request: httpx.Request) -> httpx.Request:",
                '    """Add API key to request headers."""',
                f'    api_key = os.environ.get("{env_var}", "")',
                "    if api_key:",
                f'        request.headers["{header}"] = api_key',
                "    return request",
            ]
        )
    elif auth_type == "oauth_token":
        env_var = auth_config.get("env_var", "AUTH_TOKEN")
        lines.extend(
            [
                "def apply_auth(request: httpx.Request) -> httpx.Request:",
                '    """Add Bearer token to request headers."""',
                f'    token = os.environ.get("{env_var}", "")',
                "    if token:",
                '        request.headers["Authorization"] = f"Bearer {token}"',
                "    return request",
            ]
        )
    else:
        lines.extend(
            [
                "def apply_auth(request: httpx.Request) -> httpx.Request:",
                '    """No-op auth — no credentials required."""',
                "    return request",
            ]
        )

    lines.append("")
    return "\n".join(lines)


def generate(data: dict) -> list[dict[str, str]]:
    """Generate the HTTP client files, returning ODK file dicts."""
    template_dir = Path(__file__).parent.parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    env.filters["to_snake"] = to_snake

    files: list[dict[str, str]] = []

    # __init__.py
    files.append(
        {
            "path": "src/client/__init__.py",
            "content": '"""HTTP client package."""\n\nfrom .http_client import ApiClient\n\n__all__ = ["ApiClient"]\n',
        }
    )

    # http_client.py
    template = env.get_template("client.py.j2")
    content = template.render(
        app_name=data.get("app_name", "cli"),
        base_url_env=data.get("base_url_env", "CLI_BASE_URL"),
        auth=data.get("auth", {"type": "none"}),
        groups=data.get("groups", []),
    )
    files.append({"path": "src/client/http_client.py", "content": content})

    # auth.py
    auth_content = _generate_auth(data.get("auth", {"type": "none"}))
    files.append({"path": "src/client/auth.py", "content": auth_content})

    return files


def main() -> None:
    """Entry point: load ODK components and generate client files."""
    data = load_commands_from_odk_components()
    if not data:
        emit([])
        return
    emit(generate(data))


if __name__ == "__main__":
    main()

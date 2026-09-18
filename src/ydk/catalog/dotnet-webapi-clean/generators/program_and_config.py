#!/usr/bin/env python3
"""
Generator: program-and-config
Emits the baseline ASP.NET Core Minimal API host bootstrap for the Api project:
  - Api/Program.cs                       (Minimal API hosting + DI bootstrap)
  - Api/appsettings.json
  - Api/appsettings.Development.json
  - Api/Properties/launchSettings.json

Api/ is unprefixed (no src/ nesting) to match solution_scaffold.py's Api
project directory and every other content generator in this pack.

Input: none (inputs: [] in manifest.yaml) -- always emits the same baseline
bootstrap, unconditionally.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add generators dir to path for _context imports
sys.path.insert(0, str(Path(__file__).parent))

from _context.naming import ROOT_NAMESPACE
from jinja2 import Environment, FileSystemLoader, StrictUndefined

API_DIR = "Api"


def main() -> None:
    templates_dir = Path(__file__).parent.parent / "templates" / "api"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    base_context = {"root_namespace": ROOT_NAMESPACE}

    output = [
        {
            "path": f"{API_DIR}/Program.cs",
            "content": env.get_template("program.cs.j2").render(**base_context).rstrip() + "\n",
        },
        {
            "path": f"{API_DIR}/appsettings.json",
            "content": (
                env.get_template("appsettings.json.j2")
                .render(**base_context, is_development=False, default_log_level="Information")
                .rstrip()
                + "\n"
            ),
        },
        {
            "path": f"{API_DIR}/appsettings.Development.json",
            "content": (
                env.get_template("appsettings.json.j2")
                .render(**base_context, is_development=True, default_log_level="Debug")
                .rstrip()
                + "\n"
            ),
        },
        {
            "path": f"{API_DIR}/Properties/launchSettings.json",
            "content": env.get_template("launchsettings.json.j2").render(**base_context).rstrip() + "\n",
        },
    ]

    print(json.dumps(output))


if __name__ == "__main__":
    main()

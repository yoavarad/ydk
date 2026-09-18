#!/usr/bin/env python3
"""
Generator: solution-scaffold
Emits the baseline .NET solution/project skeleton for the dotnet-webapi-clean pack:
  - {Solution}.sln
  - Domain/{Solution}.Domain.csproj
  - Application/{Solution}.Application.csproj
  - Infrastructure/{Solution}.Infrastructure.csproj
  - Api/{Solution}.Api.csproj
  - {Solution}.Tests/{Solution}.Tests.csproj
  - .editorconfig
  - Directory.Build.props

Project directories are unprefixed (no src/ or tests/ nesting) to match the
paths every content generator across this pack already emits (Domain/,
Application/, Infrastructure/, Api/, {Solution}.Tests/), so generated .cs
files land inside each project's default SDK-style compile glob.

TargetFramework is net8.0 (set via Directory.Build.props). Infrastructure
references the SQLite EF Core provider (Microsoft.EntityFrameworkCore.Sqlite).

Input: none (inputs: [] in manifest.yaml) -- always emits the same baseline
skeleton, unconditionally.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

# Add generators dir to path for _context imports
sys.path.insert(0, str(Path(__file__).parent))

from _context.naming import ROOT_NAMESPACE
from jinja2 import Environment, FileSystemLoader, StrictUndefined

# .sln project-type GUID for C# SDK-style projects.
CSHARP_PROJECT_TYPE_GUID = "{FAE04EC0-301F-11D3-BF4B-0000F81FE1F7}"

# Fixed namespace UUID (uuid.NAMESPACE_DNS) used to derive stable, deterministic
# per-project GUIDs so repeated generator runs produce byte-identical output.
_GUID_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

PROJECT_DEFS = [
    {"key": "domain", "suffix": "Domain", "dir": "Domain", "template": "domain.csproj.j2"},
    {"key": "application", "suffix": "Application", "dir": "Application", "template": "application.csproj.j2"},
    {
        "key": "infrastructure",
        "suffix": "Infrastructure",
        "dir": "Infrastructure",
        "template": "infrastructure.csproj.j2",
    },
    {"key": "api", "suffix": "Api", "dir": "Api", "template": "api.csproj.j2"},
    {"key": "tests", "suffix": "Tests", "dir": None, "template": "tests.csproj.j2"},
]


def _stable_guid(name: str) -> str:
    """Deterministic, uppercase, brace-wrapped GUID for `name` (.sln format)."""
    return f"{{{str(uuid.uuid5(_GUID_NAMESPACE, name)).upper()}}}"


def build_context() -> dict:
    projects = []
    for defn in PROJECT_DEFS:
        name = f"{ROOT_NAMESPACE}.{defn['suffix']}"
        project_dir = defn["dir"] or name
        projects.append(
            {
                "key": defn["key"],
                "name": name,
                "dir": project_dir,
                "template": defn["template"],
                "guid": _stable_guid(name),
                "type_guid": CSHARP_PROJECT_TYPE_GUID,
            }
        )
    return {
        "root_namespace": ROOT_NAMESPACE,
        "solution_name": ROOT_NAMESPACE,
        "solution_guid": _stable_guid(f"{ROOT_NAMESPACE}.sln"),
        "projects": projects,
    }


def main() -> None:
    templates_dir = Path(__file__).parent.parent / "templates" / "solution"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    context = build_context()

    output = [
        {
            "path": f"{context['solution_name']}.sln",
            "content": env.get_template("webapiclean.sln.j2").render(**context).rstrip() + "\n",
        },
        {
            "path": ".editorconfig",
            "content": env.get_template(".editorconfig.j2").render(**context).rstrip() + "\n",
        },
        {
            "path": "Directory.Build.props",
            "content": env.get_template("Directory.Build.props.j2").render(**context).rstrip() + "\n",
        },
    ]

    for project in context["projects"]:
        output.append(
            {
                "path": f"{project['dir']}/{project['name']}.csproj",
                "content": env.get_template(project["template"]).render(**context).rstrip() + "\n",
            }
        )

    print(json.dumps(output))


if __name__ == "__main__":
    main()

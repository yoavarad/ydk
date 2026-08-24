#!/usr/bin/env python3
"""Verification plugin: dotnet format.

Verifies .NET code formatting via ``dotnet format --verify-no-changes``
against the discovered solution/project. Skips gracefully when the .NET
SDK or a solution/project file isn't present, mirroring the fail-open
behavior of the built-in lint-ruff plugin for non-matching project types.
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

_EXCLUDED_DIR_PARTS = {"bin", "obj", ".git", ".ydk", ".vs", "node_modules"}
_DOTNET_EXTENSIONS = (".cs", ".csproj", ".sln")


def _has_sdk(dotnet_bin: str) -> bool:
    """Check that an actual .NET SDK is installed, not just the dotnet muxer.

    On Windows the ``dotnet`` executable can exist (bundled with the OS or
    a prior VS install) while no SDK is registered underneath it, in which
    case ``dotnet format`` fails with "No .NET SDKs were found."
    """
    try:
        result = subprocess.run(
            [dotnet_bin, "--list-sdks"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _find_format_target(project_root: str) -> str | None:
    """Find a .sln first, else the first .csproj, skipping build-output dirs.

    Deliberately excludes ``.slnx`` (the newer XML solution format): the
    .NET 8 SDK's ``dotnet format`` CLI doesn't understand it yet and fails
    with "MSB4068: The element <Solution> is unrecognized" even though the
    file itself is valid. Falling through to a ``.csproj`` avoids that.
    """
    root = Path(project_root)
    matches = sorted(p for p in root.rglob("*.sln") if not _EXCLUDED_DIR_PARTS & set(p.parts))
    if matches:
        return str(matches[0])
    matches = sorted(p for p in root.rglob("*.csproj") if not _EXCLUDED_DIR_PARTS & set(p.parts))
    if matches:
        return str(matches[0])
    return None


def main() -> None:
    """Run the dotnet-format verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    changed_files = context.get("changed_files")
    if changed_files and not any(f.lower().endswith(_DOTNET_EXTENSIONS) for f in changed_files):
        result = {
            "name": "dotnet-format",
            "passed": True,
            "output": "No .cs/.csproj/.sln files changed — skipped",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)
        return

    dotnet_bin = shutil.which("dotnet")
    if dotnet_bin is None or not _has_sdk(dotnet_bin):
        result = {
            "name": "dotnet-format",
            "passed": True,
            "output": "dotnet SDK not found — skipped (install from https://aka.ms/dotnet/download)",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)
        return

    target = _find_format_target(project_root)
    if target is None:
        result = {
            "name": "dotnet-format",
            "passed": True,
            "output": "No .sln/.csproj found — skipped (non-.NET project?)",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)
        return

    format_result = subprocess.run(
        [dotnet_bin, "format", target, "--verify-no-changes"],
        capture_output=True,
        text=True,
        cwd=project_root,
        timeout=110,
        check=False,
    )
    output = format_result.stdout + ("\n" + format_result.stderr if format_result.stderr else "")
    passed = format_result.returncode == 0

    result = {
        "name": "dotnet-format",
        "passed": passed,
        "output": output.strip(),
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"target": target},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

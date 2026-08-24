#!/usr/bin/env python3
"""Verification plugin: dotnet test.

Runs the .NET test suite via ``dotnet test``. Skips gracefully when the
.NET SDK isn't installed or no test project exists yet, mirroring the
fail-open behavior of the built-in tests-pytest plugin.
"""

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

_EXCLUDED_DIR_PARTS = {"bin", "obj", ".git", ".ydk", ".vs", "node_modules"}
_TEST_PROJECT_MARKERS = ("Test", "Tests")
_DOTNET_EXTENSIONS = (".cs", ".csproj", ".sln")


def _has_sdk(dotnet_bin: str) -> bool:
    """Check that an actual .NET SDK is installed, not just the dotnet muxer.

    On Windows the ``dotnet`` executable can exist (bundled with the OS or
    a prior VS install) while no SDK is registered underneath it, in which
    case ``dotnet test`` fails with "No .NET SDKs were found."
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


def _find_test_target(project_root: str) -> str | None:
    """Prefer a .sln (dotnet test filters to test projects automatically);
    else the first .csproj whose name looks like a test project.

    Deliberately excludes ``.slnx`` (the newer XML solution format): the
    .NET 8 SDK's ``dotnet test`` CLI doesn't understand it yet and fails
    with "MSB4068: The element <Solution> is unrecognized" even though the
    file itself is valid. Falling through to a ``.csproj`` avoids that.
    """
    root = Path(project_root)
    matches = sorted(p for p in root.rglob("*.sln") if not _EXCLUDED_DIR_PARTS & set(p.parts))
    if matches:
        return str(matches[0])
    csprojs = [p for p in root.rglob("*.csproj") if not _EXCLUDED_DIR_PARTS & set(p.parts)]
    test_projects = sorted(p for p in csprojs if any(marker in p.stem for marker in _TEST_PROJECT_MARKERS))
    if test_projects:
        return str(test_projects[0])
    return None


def main() -> None:
    """Run the dotnet-test verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    changed_files = context.get("changed_files")
    if changed_files and not any(f.lower().endswith(_DOTNET_EXTENSIONS) for f in changed_files):
        result = {
            "name": "dotnet-test",
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
            "name": "dotnet-test",
            "passed": True,
            "output": "dotnet SDK not found — skipped (install from https://aka.ms/dotnet/download)",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)
        return

    target = _find_test_target(project_root)
    if target is None:
        result = {
            "name": "dotnet-test",
            "passed": True,
            "output": "No test project (*Test*.csproj) or .sln found — skipped",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)
        return

    test_result = subprocess.run(
        [dotnet_bin, "test", target, "--nologo"],
        capture_output=True,
        text=True,
        cwd=project_root,
        timeout=290,
        check=False,
    )
    output = test_result.stdout + ("\n" + test_result.stderr if test_result.stderr else "")
    passed = test_result.returncode == 0

    detail: dict[str, object] = {"target": target}
    match = re.search(r"Passed!\s*-\s*Failed:\s*(\d+),\s*Passed:\s*(\d+)", output)
    if match:
        detail["failed"] = int(match.group(1))
        detail["passed_count"] = int(match.group(2))

    result = {
        "name": "dotnet-test",
        "passed": passed,
        "output": output.strip(),
        "duration_seconds": round(time.time() - start, 1),
        "detail": detail,
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

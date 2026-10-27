#!/usr/bin/env python3
"""Verification plugin: dotnet build.

Builds the .NET solution (.sln, or .slnx when the SDK supports it) via
``dotnet build``; with no solution, builds all discovered .csproj files.
Skips gracefully when the .NET SDK or a solution/project file isn't
present, mirroring the fail-open behavior of the built-in lint-ruff /
tests-pytest plugins for non-matching project types.
"""

import importlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_dotnet_target = importlib.import_module("_dotnet_target")


def _has_sdk(dotnet_bin: str) -> bool:
    """Check that an actual .NET SDK is installed, not just the dotnet muxer.

    On Windows the ``dotnet`` executable can exist (bundled with the OS or
    a prior VS install) while no SDK is registered underneath it, in which
    case ``dotnet build`` fails with "No .NET SDKs were found."
    """
    try:
        result = subprocess.run(
            [dotnet_bin, "--list-sdks"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _invalid_target_result(name: str, target: str, problem: str, start: float) -> dict:
    return {
        "name": name,
        "passed": False,
        "output": problem,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"target": target},
    }


def main() -> None:
    """Run the dotnet-build verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    changed_files = context.get("changed_files")
    if changed_files and not _dotnet_target.affects_dotnet_build(changed_files):
        result = {
            "name": "dotnet-build",
            "passed": True,
            "output": _dotnet_target.SKIP_MESSAGE,
            "duration_seconds": round(time.time() - start, 1),
            "detail": {"status": "SKIPPED", "skip_reason": _dotnet_target.SKIP_MESSAGE},
        }
        json.dump(result, sys.stdout)
        sys.exit(0)
        return

    dotnet_bin = shutil.which("dotnet")
    if dotnet_bin is None or not _has_sdk(dotnet_bin):
        result = {
            "name": "dotnet-build",
            "passed": True,
            "output": "dotnet SDK not found — skipped (install from https://aka.ms/dotnet/download)",
            "duration_seconds": round(time.time() - start, 1),
            "detail": {
                "status": "SKIPPED",
                "skip_reason": "dotnet SDK not found — skipped (install from https://aka.ms/dotnet/download)",
            },
        }
        json.dump(result, sys.stdout)
        sys.exit(0)
        return

    configured = _dotnet_target.configured_target(context)
    problem = _dotnet_target.target_problem(configured) if configured is not None else None
    if configured is not None and problem is not None:
        json.dump(_invalid_target_result("dotnet-build", configured, problem, start), sys.stdout)
        sys.exit(1)
        return
    targets = [configured] if configured else _dotnet_target.find_targets(project_root, dotnet_bin)
    if not targets:
        result = {
            "name": "dotnet-build",
            "passed": True,
            "output": "No .sln/.slnx/.csproj found — skipped (non-.NET project?)",
            "duration_seconds": round(time.time() - start, 1),
            "detail": {
                "status": "SKIPPED",
                "skip_reason": "No .sln/.slnx/.csproj found — skipped (non-.NET project?)",
            },
        }
        json.dump(result, sys.stdout)
        sys.exit(0)
        return

    outputs: list[str] = []
    passed = True
    deadline = start + 110
    for target in targets:
        try:
            build_result = subprocess.run(
                [dotnet_bin, "build", target, "--nologo"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=project_root,
                timeout=max(1.0, deadline - time.time()),
                check=False,
            )
        except subprocess.TimeoutExpired:
            outputs.append((f"== {target} ==\n" if len(targets) > 1 else "") + f"timed out after budget: {target}")
            passed = False
            break
        output = build_result.stdout + ("\n" + build_result.stderr if build_result.stderr else "")
        outputs.append((f"== {target} ==\n" if len(targets) > 1 else "") + output.strip())
        passed = passed and build_result.returncode == 0

    detail: dict = {"targets": targets}
    if len(targets) == 1:
        detail["target"] = targets[0]
    result = {
        "name": "dotnet-build",
        "passed": passed,
        "output": "\n".join(outputs),
        "duration_seconds": round(time.time() - start, 1),
        "detail": detail,
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

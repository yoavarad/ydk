#!/usr/bin/env python3
"""Verification plugin: dotnet test.

Runs the .NET test suite via ``dotnet test``: the configured
``verification.dotnet.target`` or, failing that, every target found by the
shared ``_dotnet_target`` helper (a solution, else all test projects), one
``dotnet test`` run per target. Skips gracefully when the .NET SDK isn't
installed or no test project exists yet, mirroring the fail-open behavior of
the built-in tests-pytest plugin.
"""

import importlib
import json
import re
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
    case ``dotnet test`` fails with "No .NET SDKs were found."
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
    """Run the dotnet-test verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    changed_files = context.get("changed_files")
    if changed_files and not _dotnet_target.affects_dotnet_build(changed_files):
        result = {
            "name": "dotnet-test",
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
            "name": "dotnet-test",
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
        json.dump(_invalid_target_result("dotnet-test", configured, problem, start), sys.stdout)
        sys.exit(1)
        return
    targets = [configured] if configured else _dotnet_target.find_targets(project_root, dotnet_bin, test_only=True)
    if not targets:
        skip_text = "No test project (*Test*.csproj) or .sln/.slnx found — skipped"
        result = {
            "name": "dotnet-test",
            "passed": True,
            "output": skip_text,
            "duration_seconds": round(time.time() - start, 1),
            "detail": {"status": "SKIPPED", "skip_reason": skip_text},
        }
        json.dump(result, sys.stdout)
        sys.exit(0)
        return

    outputs: list[str] = []
    passed = True
    deadline = start + 290
    for target in targets:
        try:
            test_result = subprocess.run(
                [dotnet_bin, "test", target, "--nologo"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=project_root,
                timeout=max(1.0, deadline - time.time()),
                check=False,
            )
        except subprocess.TimeoutExpired:
            msg = f"timed out after budget: {target}"
            outputs.append(f"== {target} ==\n{msg}" if len(targets) > 1 else msg)
            passed = False
            break
        text = test_result.stdout + ("\n" + test_result.stderr if test_result.stderr else "")
        outputs.append(f"== {target} ==\n{text}" if len(targets) > 1 else text)
        passed = passed and test_result.returncode == 0
    output = "\n".join(outputs)

    detail: dict[str, object] = {"targets": targets}
    if len(targets) == 1:
        detail["target"] = targets[0]
    matches = list(re.finditer(r"(?:Passed|Failed)!\s*-\s*Failed:\s*(\d+),\s*Passed:\s*(\d+)", output))
    if matches:
        detail["failed"] = sum(int(m.group(1)) for m in matches)
        detail["passed_count"] = sum(int(m.group(2)) for m in matches)

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

#!/usr/bin/env python3
"""Verification plugin: ruff format check + ruff lint + ty type checking.

Converted from fastapi-protocol-hexagonal check_quality.sh.
Runs full-project mode only (pre_commit/on_demand).
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

RUFF_SELECT = "E,F,I,ANN001,ANN002,ANN201,ANN202,ANN401,B,UP,RUF,PT,SIM,PERF,FAST,D101,D102,D103"


def main() -> None:
    """Run the python-quality verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    config = context.get("config", {})
    auto_fix = config.get("auto_fix", False)
    start = time.time()

    failures = 0
    messages: list[str] = []

    root = Path(project_root)

    # Determine ruff binary
    venv_ruff = root / ".venv" / "bin" / "ruff"
    ruff_cmd = str(venv_ruff) if venv_ruff.is_file() else "ruff"

    # Determine ty binary
    venv_ty = root / ".venv" / "bin" / "ty"
    ty_cmd = str(venv_ty) if venv_ty.is_file() else "ty"

    src_dirs = [d for d in ["app", "src"] if (root / d).is_dir()]
    test_dir = "tests" if (root / "tests").is_dir() else None

    check_dirs = src_dirs + ([test_dir] if test_dir else [])
    if not check_dirs:
        check_dirs = ["."]

    # ruff format
    if auto_fix:
        subprocess.run(
            [ruff_cmd, "format", *check_dirs],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
    fmt_result = subprocess.run(
        [ruff_cmd, "format", "--check", *check_dirs],
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    if fmt_result.returncode != 0:
        messages.append(f"FAIL: ruff format -- run: ruff format {' '.join(check_dirs)}")
        messages.append(fmt_result.stdout.strip())
        failures += 1

    # ruff lint
    if auto_fix:
        subprocess.run(
            [ruff_cmd, "check", *check_dirs, "--select", RUFF_SELECT, "--fix"],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
    lint_result = subprocess.run(
        [ruff_cmd, "check", *check_dirs, "--select", RUFF_SELECT],
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    if lint_result.returncode != 0:
        messages.append("FAIL: ruff lint:")
        messages.append(lint_result.stdout.strip())
        failures += 1

    # ty -- full project (src dirs only, skip tests to avoid false positives)
    if shutil.which(ty_cmd) or Path(ty_cmd).is_file():
        ty_result = subprocess.run(
            [ty_cmd, "check", *src_dirs, "--python-version", "3.12"],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        ty_output = ty_result.stdout + (("\n" + ty_result.stderr) if ty_result.stderr else "")
        if "error[" in ty_output:
            messages.append("FAIL: ty:")
            messages.append(ty_output.strip())
            failures += 1

    passed = failures == 0
    if passed:
        output = "PASS: format, lint, and type checks clean"
    else:
        output = "\n".join(messages) + f"\n{failures} quality check(s) failed"

    result = {
        "name": "python-quality",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

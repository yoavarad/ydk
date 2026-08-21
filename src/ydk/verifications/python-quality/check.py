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

RUFF_SELECT = "E,F,I,ANN001,ANN002,ANN201,ANN202,ANN401,B,UP,RUF,PT,SIM,PERF,FAST,D101,D102,D103,TC"


def _resolve_venv_binary(project_root: str, tool: str) -> str:
    """Resolve ``tool`` to the project's own venv when present, else bare name for PATH.

    A bare PATH lookup can resolve a different, unrelated installation (e.g.
    a global Python's Scripts directory) ahead of the project's own
    virtualenv, silently running checks against the wrong environment.
    """
    venv_dir = "Scripts" if sys.platform == "win32" else "bin"
    suffix = ".exe" if sys.platform == "win32" else ""
    candidate = Path(project_root) / ".venv" / venv_dir / f"{tool}{suffix}"
    return str(candidate) if candidate.is_file() else tool


def _discover_ty_dirs(project_root: str, src_dirs: list[str]) -> list[str]:
    """Narrow ``src_dirs`` for ty specifically, expanding around a catalog directory.

    A ``src/ydk/catalog`` directory (this project's own scaffolding templates
    for other projects) is expanded around rather than passed as part of
    ``src`` -- those templates aren't first-party source and commonly fail
    type checking in isolation. ty's own ``--exclude`` flag proved unreliable
    for this in practice, so it's excluded by omission instead. Only affects
    the ty invocation -- ruff still formats/lints the catalog normally.
    """
    root = Path(project_root)
    catalog = root / "src" / "ydk" / "catalog"
    if "src" not in src_dirs or not catalog.is_dir():
        return src_dirs

    dirs = [d for d in src_dirs if d != "src"]
    dirs += sorted(
        f"src/ydk/{child.name}"
        for child in (root / "src" / "ydk").iterdir()
        if child != catalog and child.name != "__pycache__"
    )
    return dirs


def _build_ty_cmd(ty_cmd: str, project_root: str, src_dirs: list[str]) -> list[str]:
    """Build the ``ty check`` command."""
    ty_dirs = _discover_ty_dirs(project_root, src_dirs)
    return [ty_cmd, "check", *ty_dirs, "--python-version", "3.12"]


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
    ruff_cmd = _resolve_venv_binary(project_root, "ruff")
    ty_cmd = _resolve_venv_binary(project_root, "ty")

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
            _build_ty_cmd(ty_cmd, project_root, src_dirs),
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

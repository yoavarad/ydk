#!/usr/bin/env python3
"""Verification plugin: ty type checking.

When changed_files is provided in context, only checks those Python files
instead of the entire project. This prevents generated files from blocking
verification on task branches.
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _discover_src_dirs(project_root: str) -> list[str]:
    """Discover source directories that exist in the project.

    A ``src/ydk/catalog`` directory (this project's own scaffolding templates
    for other projects) is expanded around rather than passed as part of
    ``src`` -- those templates aren't first-party source and commonly fail
    type checking in isolation. ty's own ``--exclude`` flag proved unreliable
    for this in practice, so it's excluded by omission instead.
    """
    root = Path(project_root)
    dirs = [d for d in ["src", "app"] if (root / d).is_dir()]
    if not dirs:
        return ["."]

    catalog = root / "src" / "ydk" / "catalog"
    if "src" in dirs and catalog.is_dir():
        dirs.remove("src")
        dirs += sorted(
            f"src/ydk/{child.name}"
            for child in (root / "src" / "ydk").iterdir()
            if child != catalog and child.name != "__pycache__"
        )
    return dirs


def _resolve_ty(project_root: str) -> str | None:
    """Resolve the ``ty`` binary, preferring the project's own venv over PATH.

    A bare PATH lookup can resolve a different, unrelated installation (e.g.
    a global Python's Scripts directory) ahead of the project's own
    virtualenv, silently running the check against the wrong environment.
    """
    venv_dir = "Scripts" if sys.platform == "win32" else "bin"
    suffix = ".exe" if sys.platform == "win32" else ""
    candidate = Path(project_root) / ".venv" / venv_dir / f"ty{suffix}"
    if candidate.is_file():
        return str(candidate)
    return shutil.which("ty")


def _build_cmd(ty_bin: str, project_root: str, py_files: list[str] | None) -> list[str]:
    """Build the ``ty check`` command, scoped to changed files when given."""
    if py_files is not None:
        return [ty_bin, "check", "--project", project_root, *py_files]

    src_dirs = _discover_src_dirs(project_root)
    return [ty_bin, "check", "--project", project_root, *src_dirs]


def main() -> None:
    """Run the types-ty verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    ty_bin = _resolve_ty(project_root)

    # Skip gracefully when ty isn't installed (e.g. non-Python project)
    if ty_bin is None:
        check_result = {
            "name": "types-ty",
            "passed": True,
            "output": "ty not found on PATH — skipped (non-Python project?)",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(check_result, sys.stdout)
        sys.exit(0)
        return

    # Scope to changed files when available (avoids blocking on generated file errors)
    changed_files = context.get("changed_files")
    if changed_files:
        py_files = [f for f in changed_files if f.endswith(".py")]
        if not py_files:
            # No Python files changed, skip type checking
            check_result = {
                "name": "types-ty",
                "passed": True,
                "output": "No Python files changed — skipped",
                "duration_seconds": round(time.time() - start, 1),
                "detail": None,
            }
            json.dump(check_result, sys.stdout)
            sys.exit(0)
            return
        cmd = _build_cmd(ty_bin, project_root, py_files)
    else:
        cmd = _build_cmd(ty_bin, project_root, None)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    output = result.stdout
    if result.stderr:
        output += "\n" + result.stderr

    passed = result.returncode == 0
    check_result = {
        "name": "types-ty",
        "passed": passed,
        "output": output.strip(),
        "duration_seconds": round(time.time() - start, 1),
        "detail": None,
    }
    json.dump(check_result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

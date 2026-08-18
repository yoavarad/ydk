#!/usr/bin/env python3
"""Verification plugin: ty type checking.

When changed_files is provided in context, only checks those Python files
instead of the entire project. This prevents generated files from blocking
verification on task branches.
"""

import json
import subprocess
import sys
import time
from pathlib import Path


def _discover_src_dirs(project_root: str) -> list[str]:
    """Discover source directories that exist in the project."""
    root = Path(project_root)
    dirs = [d for d in ["src", "app"] if (root / d).is_dir()]
    if not dirs:
        dirs = ["."]
    return dirs


def main() -> None:
    """Run the types-ty verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

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
        cmd = ["ty", "check", "--project", project_root, *py_files]
    else:
        src_dirs = _discover_src_dirs(project_root)
        cmd = ["ty", "check", "--project", project_root, *src_dirs]

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

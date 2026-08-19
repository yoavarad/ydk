#!/usr/bin/env python3
"""Verification plugin: ruff format check + ruff lint.

When the context includes ``auto_fix: true``, this plugin runs
``ruff check --fix`` and ``ruff format`` before the normal check pass.
Auto-fix modifies files on disk -- the caller is responsible for
reviewing changes before committing.
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _discover_dirs(project_root: str) -> list[str]:
    """Discover source/test directories that exist in the project."""
    root = Path(project_root)
    dirs = [d for d in ["src", "app", "tests"] if (root / d).is_dir()]
    if not dirs:
        dirs = ["."]
    return dirs


def _count_violations(output: str) -> int:
    """Count the number of violation lines in ruff output.

    Ruff outputs one line per violation with a file path prefix, then a
    summary line like "Found N errors". We count the "Found N" line when
    present, otherwise fall back to counting non-empty, non-summary lines.
    """
    for line in output.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith("Found ") and "error" in stripped:
            # "Found 5 errors." or "Found 5 errors (3 fixed, 2 remaining)."
            try:
                return int(stripped.split()[1])
            except (IndexError, ValueError):
                pass
    # Fallback: count lines that look like violations (contain a colon path)
    return sum(1 for line in output.strip().splitlines() if line.strip() and ":" in line)


def _run_auto_fix(project_root: str, check_dirs: list[str]) -> tuple[int, int]:
    """Run ruff auto-fix and ruff format, return (fixed_count, remaining_count).

    1. Count violations before fix
    2. Run ``ruff check --fix``
    3. Run ``ruff format``
    4. Count violations after fix
    5. Return (before - after, after)
    """
    # Count violations before fix
    before = subprocess.run(
        ["ruff", "check", *check_dirs],
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    before_count = _count_violations(before.stdout + before.stderr)

    # Fix lint issues
    subprocess.run(
        ["ruff", "check", "--fix", *check_dirs],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    # Fix formatting
    subprocess.run(
        ["ruff", "format", *check_dirs],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    # Count remaining violations
    after = subprocess.run(
        ["ruff", "check", *check_dirs],
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    after_count = _count_violations(after.stdout + after.stderr)

    fixed = max(0, before_count - after_count)
    return fixed, after_count


def main() -> None:
    """Run the lint-ruff verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    auto_fix = context.get("auto_fix", False)
    start = time.time()

    # Skip gracefully when ruff isn't installed (e.g. non-Python project)
    if shutil.which("ruff") is None:
        result = {
            "name": "lint-ruff",
            "passed": True,
            "output": "ruff not found on PATH — skipped (non-Python project?)",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)
        return

    # Scope to changed files when available
    changed_files = context.get("changed_files")
    if changed_files:
        py_files = [f for f in changed_files if f.endswith(".py")]
        if not py_files:
            result = {
                "name": "lint-ruff",
                "passed": True,
                "output": "No Python files changed — skipped",
                "duration_seconds": round(time.time() - start, 1),
                "detail": None,
            }
            json.dump(result, sys.stdout)
            sys.exit(0)
            return
        # Use the specific files instead of directories
        check_dirs = py_files
    else:
        check_dirs = _discover_dirs(project_root)

    auto_fixed_count = 0
    remaining_count = 0

    if auto_fix:
        auto_fixed_count, remaining_count = _run_auto_fix(project_root, check_dirs)

    # Run format check
    fmt_result = subprocess.run(
        ["ruff", "format", "--check", *check_dirs],
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    # Run lint check
    lint_result = subprocess.run(
        ["ruff", "check", *check_dirs],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    passed = fmt_result.returncode == 0 and lint_result.returncode == 0
    fmt_output = fmt_result.stdout + ("\n" + fmt_result.stderr if fmt_result.stderr else "")
    lint_output = lint_result.stdout + ("\n" + lint_result.stderr if lint_result.stderr else "")
    output = f"Format: {fmt_output.strip()}\nLint: {lint_output.strip()}"

    detail: dict[str, object] | None = None
    if auto_fix:
        detail = {
            "auto_fixed_count": auto_fixed_count,
            "remaining_count": remaining_count,
        }

    result = {
        "name": "lint-ruff",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": detail,
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

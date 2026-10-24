#!/usr/bin/env python3
"""Verification plugin: TDD guard — blocks source edits when no test has been written.

State machine phases:
- red: MUST write a test file. Source writes BLOCKED.
- green: Test was written AND run (failed). Source writes ALLOWED.
- refactor: Tests pass. Both source and test edits allowed.
"""

import json
import sys
import time
from pathlib import Path, PurePosixPath

# Directories that are always allowed (never blocked)
_ALWAYS_ALLOWED_PREFIXES = (
    "tests/",
    "docs/",
    ".ydk/",
    ".claude/",
    "scripts/",
)

# Patterns that identify test files
_TEST_FILE_PATTERNS = ("test_", "_test.py")

# Source directories that are guarded in RED phase
_SOURCE_PREFIXES = ("src/", "app/")

STATE_FILE = ".ydk/tdd-state.json"

DEFAULT_STATE = {
    "phase": "red",
    "test_files_written": [],
    "test_run_after_write": False,
    "active_task": None,
}


def _read_state(project_root: str) -> dict:
    """Read TDD state from .ydk/tdd-state.json, or return default."""
    state_path = Path(project_root) / STATE_FILE
    if state_path.exists():
        try:
            return json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            return dict(DEFAULT_STATE)
    return dict(DEFAULT_STATE)


def _write_state(project_root: str, state: dict) -> None:
    """Persist TDD state to .ydk/tdd-state.json."""
    state_path = Path(project_root) / STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))


def _matches(file_path: str, globs: list[str]) -> bool:
    """True if file_path matches any glob (``**`` spans directories)."""
    return any(PurePosixPath(file_path).full_match(g) for g in globs)


def _is_vendor(file_path: str) -> bool:
    return file_path.startswith("vendor/") or "/vendor/" in file_path


def _is_test_file(file_path: str, tdd: dict | None = None) -> bool:
    """Check if a file path is a test file."""
    tdd = tdd or {}
    if file_path.startswith("tests/"):
        return True
    basename = Path(file_path).name
    if tdd.get("test_for") == "same-dir-suffix" and basename.endswith(tdd.get("test_suffix") or "_test.go"):
        return True
    if tdd.get("test_globs") is not None:
        return _matches(file_path, tdd["test_globs"])
    return basename.startswith("test_") or basename.endswith("_test.py")


def _is_source_file(file_path: str, tdd: dict | None = None) -> bool:
    """Check if a file path is a source file that should be guarded."""
    tdd = tdd or {}
    if _is_vendor(file_path) or _matches(file_path, tdd.get("exempt_globs") or []):
        return False
    # If it's in an always-allowed prefix, it's not a guarded source file
    for prefix in _ALWAYS_ALLOWED_PREFIXES:
        if file_path.startswith(prefix):
            return False
    # If it's a test file by name pattern, it's not guarded
    if _is_test_file(file_path, tdd):
        return False
    if tdd.get("source_globs") is not None:
        return _matches(file_path, tdd["source_globs"])
    # If it starts with a known source prefix, it IS guarded
    for prefix in _SOURCE_PREFIXES:
        if file_path.startswith(prefix):
            return True
    # Files NOT under tests/, docs/, .ydk/, .claude/, scripts/ AND not matching
    # test patterns are considered source files (conservative approach)
    # Only guard if the file is a .py file in a source-like location
    return file_path.endswith(".py")


def _has_same_dir_test(project_root: str, file_path: str, tdd: dict) -> bool:
    """True if an <name><suffix> or any *<suffix> test exists next to file_path."""
    suffix = tdd.get("test_suffix") or "_test.go"
    directory = (Path(project_root) / file_path).parent
    if not directory.is_dir():
        return False
    return any(directory.glob(f"*{suffix}"))


def _state_file_exists(project_root: str) -> bool:
    """Check if .ydk/tdd-state.json exists (plugin is activated for this project)."""
    return (Path(project_root) / STATE_FILE).exists()


def main() -> None:
    """Run the tdd-guard verification check."""
    try:
        raw = sys.stdin.read()
        context = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        print(json.dumps({"name": "tdd-guard", "passed": True, "output": "PASS: stdin parse failed (fail open)"}))
        return
    project_root = context["project_root"]
    file_path = context.get("file_path", "")
    tdd = (context.get("config") or {}).get("tdd") or {}
    start = time.time()

    # If no state file exists, the TDD guard is not active for this project — pass through
    if not _state_file_exists(project_root):
        result = {
            "name": "tdd-guard",
            "passed": True,
            "output": "SKIP: TDD guard not activated (no .ydk/tdd-state.json)",
            "duration_seconds": round(time.time() - start, 3),
            "detail": {"status": "SKIPPED", "skip_reason": "SKIP: TDD guard not activated (no .ydk/tdd-state.json)"},
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    state = _read_state(project_root)
    phase = state.get("phase", "red")
    test_files_written = state.get("test_files_written", [])
    test_run_after_write = state.get("test_run_after_write", False)

    passed = True
    output = "OK"

    # Rule 1: Non-source files always allowed
    if not _is_source_file(file_path, tdd):
        # If it's a test file, record it
        if _is_test_file(file_path, tdd) and file_path not in test_files_written:
            test_files_written.append(file_path)
            state["test_files_written"] = test_files_written
            _write_state(project_root, state)
        passed = True
        output = f"PASS: '{file_path}' is not a guarded source file"
    # Rule 2: Source file in green or refactor phase -> allowed
    elif phase in ("green", "refactor"):
        passed = True
        output = f"PASS: source edit allowed in '{phase}' phase"
    # Rule 2b: same-dir strategy - a test must already exist next to the source file
    elif (
        phase == "red"
        and tdd.get("test_for") == "same-dir-suffix"
        and not _has_same_dir_test(project_root, file_path, tdd)
    ):
        passed = False
        suffix = tdd.get("test_suffix") or "_test.go"
        output = (
            f"BLOCKED: cannot edit source file '{file_path}' in RED phase. "
            f"Write a failing test (*{suffix}) in the same directory first."
        )
    # Rule 3: Source file in red phase with tests written AND run -> transition to green
    elif phase == "red" and test_files_written and test_run_after_write:
        state["phase"] = "green"
        _write_state(project_root, state)
        passed = True
        output = "PASS: transitioning to 'green' phase — source edit allowed"
    # Rule 4: Source file in red phase -> BLOCKED
    elif phase == "red":
        passed = False
        if not test_files_written:
            output = (
                f"BLOCKED: cannot edit source file '{file_path}' in RED phase. Write a test first (tests/ directory)."
            )
        else:
            output = (
                f"BLOCKED: cannot edit source file '{file_path}' in RED phase. "
                "Tests written but not yet run. Run pytest first."
            )
    else:
        # Unknown phase — allow but warn
        passed = True
        output = f"WARN: unknown phase '{phase}', allowing edit"

    result = {
        "name": "tdd-guard",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 3),
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

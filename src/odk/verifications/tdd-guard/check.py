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
from pathlib import Path

# Directories that are always allowed (never blocked)
_ALWAYS_ALLOWED_PREFIXES = (
    "tests/",
    "docs/",
    ".odk/",
    ".claude/",
    "scripts/",
)

# Patterns that identify test files
_TEST_FILE_PATTERNS = ("test_", "_test.py")

# Source directories that are guarded in RED phase
_SOURCE_PREFIXES = ("src/", "app/")

STATE_FILE = ".odk/tdd-state.json"

DEFAULT_STATE = {
    "phase": "red",
    "test_files_written": [],
    "test_run_after_write": False,
    "active_task": None,
}


def _read_state(project_root: str) -> dict:
    """Read TDD state from .odk/tdd-state.json, or return default."""
    state_path = Path(project_root) / STATE_FILE
    if state_path.exists():
        try:
            return json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            return dict(DEFAULT_STATE)
    return dict(DEFAULT_STATE)


def _write_state(project_root: str, state: dict) -> None:
    """Persist TDD state to .odk/tdd-state.json."""
    state_path = Path(project_root) / STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))


def _is_test_file(file_path: str) -> bool:
    """Check if a file path is a test file."""
    if file_path.startswith("tests/"):
        return True
    basename = Path(file_path).name
    return basename.startswith("test_") or basename.endswith("_test.py")


def _is_source_file(file_path: str) -> bool:
    """Check if a file path is a source file that should be guarded."""
    # If it's in an always-allowed prefix, it's not a guarded source file
    for prefix in _ALWAYS_ALLOWED_PREFIXES:
        if file_path.startswith(prefix):
            return False
    # If it's a test file by name pattern, it's not guarded
    if _is_test_file(file_path):
        return False
    # If it starts with a known source prefix, it IS guarded
    for prefix in _SOURCE_PREFIXES:
        if file_path.startswith(prefix):
            return True
    # Files NOT under tests/, docs/, .odk/, .claude/, scripts/ AND not matching
    # test patterns are considered source files (conservative approach)
    # Only guard if the file is a .py file in a source-like location
    return file_path.endswith(".py")


def _state_file_exists(project_root: str) -> bool:
    """Check if .odk/tdd-state.json exists (plugin is activated for this project)."""
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
    start = time.time()

    # If no state file exists, the TDD guard is not active for this project — pass through
    if not _state_file_exists(project_root):
        result = {
            "name": "tdd-guard",
            "passed": True,
            "output": "SKIP: TDD guard not activated (no .odk/tdd-state.json)",
            "duration_seconds": round(time.time() - start, 3),
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
    if not _is_source_file(file_path):
        # If it's a test file, record it
        if _is_test_file(file_path) and file_path not in test_files_written:
            test_files_written.append(file_path)
            state["test_files_written"] = test_files_written
            _write_state(project_root, state)
        passed = True
        output = f"PASS: '{file_path}' is not a guarded source file"
    # Rule 2: Source file in green or refactor phase -> allowed
    elif phase in ("green", "refactor"):
        passed = True
        output = f"PASS: source edit allowed in '{phase}' phase"
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

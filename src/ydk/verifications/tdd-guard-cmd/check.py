#!/usr/bin/env python3
"""Verification plugin: TDD guard command tracker.

Tracks test-command execution (tdd.test_commands, default pytest) and
git commit commands to advance the TDD state machine. Always passes (never blocks commands).

Transitions:
- pytest detected + test_files_written non-empty → phase becomes 'green'
- git commit detected → reset state to 'red' (new TDD cycle)
"""

import json
import re
import sys
import time
from pathlib import Path

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


DEFAULT_TEST_COMMANDS = [r"\bpytest\b"]


def _compile_patterns(context: dict) -> list[re.Pattern[str]]:
    """Compile configured tdd.test_commands; fall back to the default if none are usable."""
    configured = ((context.get("config") or {}).get("tdd") or {}).get("test_commands")
    compiled: list[re.Pattern[str]] = []
    if isinstance(configured, list):
        for pattern in configured:
            try:
                compiled.append(re.compile(pattern))
            except (re.error, TypeError):
                continue
    return compiled or [re.compile(p) for p in DEFAULT_TEST_COMMANDS]


def _is_test_command(command: str, patterns: list[re.Pattern[str]]) -> bool:
    """Check if a command matches any test-command regex."""
    return any(p.search(command) for p in patterns)


def _is_git_commit_command(command: str) -> bool:
    """Check if a command is a git commit."""
    return "git commit" in command or "git c " in command


def main() -> None:
    """Run the tdd-guard-cmd verification check."""
    try:
        raw = sys.stdin.read()
        context = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        print(json.dumps({"name": "tdd-guard-cmd", "passed": True, "output": "PASS: stdin parse failed (fail open)"}))
        return
    project_root = context["project_root"]
    command = context.get("command", "")
    start = time.time()

    # If no state file exists, the TDD guard is not active for this project — pass through
    state_path = Path(project_root) / STATE_FILE
    if not state_path.exists():
        result = {
            "name": "tdd-guard-cmd",
            "passed": True,
            "output": "SKIP: TDD guard not activated (no .ydk/tdd-state.json)",
            "duration_seconds": round(time.time() - start, 3),
            "detail": {"status": "SKIPPED", "skip_reason": "SKIP: TDD guard not activated (no .ydk/tdd-state.json)"},
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    state = _read_state(project_root)
    output = "OK: command allowed"

    if _is_test_command(command, _compile_patterns(context)):
        # Mark that pytest was run after tests were written
        state["test_run_after_write"] = True
        test_files_written = state.get("test_files_written", [])

        if test_files_written and state.get("phase") == "red":
            # Optimistic transition: pytest is about to run with tests written
            # Transition to green (Option A — pre-push is the safety net)
            state["phase"] = "green"
            output = "OK: pytest detected — transitioning to 'green' phase"
        elif state.get("phase") == "green":
            # In green phase, running pytest after source edits
            # Optimistically transition to refactor (tests should pass now)
            state["phase"] = "refactor"
            output = "OK: pytest detected in 'green' phase — transitioning to 'refactor'"
        else:
            output = "OK: pytest execution tracked"

        _write_state(project_root, state)

    elif _is_git_commit_command(command):
        # Reset to RED — new TDD cycle
        state = {
            "phase": "red",
            "test_files_written": [],
            "test_run_after_write": False,
            "active_task": state.get("active_task"),
        }
        _write_state(project_root, state)
        output = "OK: git commit detected — resetting to 'red' phase"

    # Always pass — we never block commands, just track state
    result = {
        "name": "tdd-guard-cmd",
        "passed": True,
        "output": output,
        "duration_seconds": round(time.time() - start, 3),
    }
    json.dump(result, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()

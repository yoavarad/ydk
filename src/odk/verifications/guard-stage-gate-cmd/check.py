#!/usr/bin/env python3
"""Guard plugin: block ODK commands inappropriate for the current development stage."""

import json
import sys
import time
from pathlib import Path

# Stage rules for commands: maps stage -> (blocked_commands, allowed_commands)
# blocked_commands: list of command prefixes that are blocked
# allowed_commands: list of command prefixes that are explicitly allowed
# If a command matches a blocked prefix but NOT an allowed prefix, it is blocked.
_STAGE_CMD_RULES: dict[str, dict[str, list[str]]] = {
    "01": {
        "blocked": ["odk ignite", "odk task create", "odk task start"],
        "allowed": ["odk component", "odk spec", "odk catalog"],
    },
    "01.5": {
        "blocked": ["odk task create-batch", "odk task start"],
        "allowed": ["odk ignite", "odk todo list", "ruff", "pytest --collect-only"],
    },
    "02": {
        "blocked": ["odk ignite"],
        "allowed": ["odk task", "odk todo"],
    },
    "03": {
        "blocked": ["odk ignite"],
        "allowed": ["odk task", "odk verify", "pytest", "ruff"],
    },
}

# Human-readable stage names
_STAGE_NAMES: dict[str, str] = {
    "00": "setup",
    "01": "brainstorm",
    "01.5": "ignition",
    "02": "planning",
    "03": "execution",
    "04": "learning",
}


def _is_command_blocked(command: str, stage: str) -> tuple[bool, str]:
    """Check if a command is blocked in the given stage.

    Returns (is_blocked, explanation).
    """
    rules = _STAGE_CMD_RULES.get(stage)
    if rules is None:
        return False, ""

    blocked_commands = rules["blocked"]
    allowed_commands = rules["allowed"]

    # Check if command matches any allowed prefix first
    for prefix in allowed_commands:
        if command.startswith(prefix):
            return False, ""

    # Check if command matches any blocked prefix
    for prefix in blocked_commands:
        if command.startswith(prefix):
            stage_name = _STAGE_NAMES.get(stage, stage)
            return True, f"Stage {stage} ({stage_name}) does not allow '{prefix}'"

    return False, ""


def main() -> None:
    """Run the guard-stage-gate-cmd check."""
    try:
        raw = sys.stdin.read()
        context = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        print(
            json.dumps(
                {"name": "guard-stage-gate-cmd", "passed": True, "output": "PASS: stdin parse failed (fail open)"}
            )
        )
        return
    project_root = context.get("project_root", ".")
    start = time.time()

    root = Path(project_root)

    # Read current stage from state — if no state.json, guard is inactive
    state_path = root / ".odk" / "state.json"
    if not state_path.exists():
        result = {
            "name": "guard-stage-gate-cmd",
            "passed": True,
            "output": "PASS: no .odk/state.json — stage gate not active",
            "duration_seconds": round(time.time() - start, 1),
            "detail": {},
        }
        json.dump(result, sys.stdout)
        sys.exit(0)
    state = json.loads(state_path.read_text())

    stage = state.get("stage", "00")

    # Get the command being run from context
    command = context.get("command", "")
    if not command:
        result = {
            "name": "guard-stage-gate-cmd",
            "passed": True,
            "output": "PASS: no command to check",
            "duration_seconds": round(time.time() - start, 1),
            "detail": {},
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    blocked, explanation = _is_command_blocked(command, stage)

    if blocked:
        output = f"Stage {stage} — '{command}' not allowed. {explanation}"
        result = {
            "name": "guard-stage-gate-cmd",
            "passed": False,
            "output": output,
            "duration_seconds": round(time.time() - start, 1),
            "detail": {"stage": stage, "command": command, "blocked": True},
        }
        json.dump(result, sys.stdout)
        sys.exit(1)

    result = {
        "name": "guard-stage-gate-cmd",
        "passed": True,
        "output": f"PASS: '{command}' allowed in stage {stage}",
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"stage": stage, "command": command, "blocked": False},
    }
    json.dump(result, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()

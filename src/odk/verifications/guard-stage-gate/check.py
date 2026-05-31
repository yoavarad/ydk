#!/usr/bin/env python3
"""Guard plugin: block file edits inappropriate for the current development stage."""

import json
import sys
import time
from pathlib import Path

# Stage rules: maps stage -> (blocked_prefixes, allowed_prefixes)
# A file is blocked if it matches any blocked prefix AND does not match any allowed prefix.
_STAGE_RULES: dict[str, dict[str, list[str]]] = {
    "00": {
        "blocked": [],  # Setup stage — everything allowed
        "allowed": [""],
    },
    "01": {
        "blocked": ["src/", "app/", "tests/"],
        "allowed": ["docs/", ".odk/components/", ".odk/"],
    },
    "01.5": {
        "blocked": ["src/", "app/"],
        "allowed": [".odk/", "docs/"],
    },
    "02": {
        "blocked": ["src/", "app/", "tests/"],
        "allowed": [".odk/", "docs/"],
    },
    "03": {
        "blocked": [],  # TDD guard handles this stage
        "allowed": [""],  # Everything allowed
    },
    "04": {
        "blocked": ["src/", "app/"],
        "allowed": ["docs/", ".odk/"],
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


def _is_blocked(file_path: str, stage: str) -> tuple[bool, str]:
    """Check if a file path is blocked in the given stage.

    Returns (is_blocked, explanation).
    """
    rules = _STAGE_RULES.get(stage)
    if rules is None:
        return False, ""

    blocked_prefixes = rules["blocked"]
    allowed_prefixes = rules["allowed"]

    # Check if file matches any allowed prefix first
    for prefix in allowed_prefixes:
        if prefix == "":
            return False, ""  # Everything allowed
        if file_path.startswith(prefix):
            return False, ""

    # Check if file matches any blocked prefix
    for prefix in blocked_prefixes:
        if prefix == "":
            # Everything blocked (except already-allowed above)
            stage_name = _STAGE_NAMES.get(stage, stage)
            return True, f"Stage {stage} ({stage_name}) only allows writes to .odk/ config files"
        if file_path.startswith(prefix):
            stage_name = _STAGE_NAMES.get(stage, stage)
            return True, f"Stage {stage} ({stage_name}) does not allow writes to {prefix}* files"

    return False, ""


def main() -> None:
    """Run the guard-stage-gate check."""
    try:
        raw = sys.stdin.read()
        context = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        # Fail open — can't parse input, allow action
        print(
            json.dumps({"name": "guard-stage-gate", "passed": True, "output": "PASS: stdin parse failed (fail open)"})
        )
        return
    project_root = context.get("project_root", ".")
    start = time.time()

    root = Path(project_root)

    # Read current stage from state — if no state.json, guard is inactive
    state_path = root / ".odk" / "state.json"
    if not state_path.exists():
        result = {
            "name": "guard-stage-gate",
            "passed": True,
            "output": "PASS: no .odk/state.json — stage gate not active",
            "duration_seconds": round(time.time() - start, 1),
            "detail": {},
        }
        json.dump(result, sys.stdout)
        sys.exit(0)
    state = json.loads(state_path.read_text())

    stage = state.get("stage", "00")

    # Get the file being edited from context
    file_path = context.get("file_path", "")
    if not file_path:
        # No file path in context — pass
        result = {
            "name": "guard-stage-gate",
            "passed": True,
            "output": "PASS: no file path to check",
            "duration_seconds": round(time.time() - start, 1),
            "detail": {},
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    # Normalize: remove leading ./ or project root prefix
    if file_path.startswith("./"):
        file_path = file_path[2:]
    root_str = str(root)
    if file_path.startswith(root_str):
        file_path = file_path[len(root_str) :].lstrip("/")

    blocked, explanation = _is_blocked(file_path, stage)

    if blocked:
        output = f"Stage {stage} — edit to '{file_path}' not allowed. {explanation}"
        result = {
            "name": "guard-stage-gate",
            "passed": False,
            "output": output,
            "duration_seconds": round(time.time() - start, 1),
            "detail": {"stage": stage, "file_path": file_path, "blocked": True},
        }
        json.dump(result, sys.stdout)
        sys.exit(1)

    result = {
        "name": "guard-stage-gate",
        "passed": True,
        "output": f"PASS: '{file_path}' allowed in stage {stage}",
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"stage": stage, "file_path": file_path, "blocked": False},
    }
    json.dump(result, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()

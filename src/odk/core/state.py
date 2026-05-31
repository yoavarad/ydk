"""Project state tracking for guards and gates."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class ProjectState:
    """Read/write project state from .odk/state.json."""

    def __init__(self, project_root: Path) -> None:
        self._path = project_root / ".odk" / "state.json"

    @property
    def path(self) -> Path:
        """Path to the state file."""
        return self._path

    def read(self) -> dict:
        """Read current state. Returns default if no file exists."""
        if not self._path.exists():
            return {"stage": "00"}
        return json.loads(self._path.read_text())

    def write(self, state: dict) -> None:
        """Write state to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(state, indent=2))

    def update(self, **kwargs: object) -> dict:
        """Merge kwargs into current state and persist."""
        state = self.read()
        state.update(kwargs)
        self.write(state)
        return state

"""Manifest file management — quick index of all items + statuses.

The manifest is the source of truth for IDs and status lookups,
avoiding the need to parse individual markdown files for listings.
"""

from __future__ import annotations

import re
import threading
import uuid
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from pathlib import Path

_LEGACY_ID_RE = re.compile(r"^[TSE]-(\d{3})$")


def _generate_hash_id(prefix: str) -> str:
    """Generate a collision-resistant ID like ``T-a1b2c3d4``.

    Uses uuid4 (timestamp + random bytes) truncated to 8 hex characters.
    """
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def parse_number_from_id(item_id: str) -> int:
    """Extract a numeric value from a legacy sequential ID.

    Returns the integer for legacy IDs (e.g. ``T-001`` -> ``1``).
    Returns ``0`` for hash-based IDs (e.g. ``T-a1b2c3d4`` -> ``0``).
    """
    match = _LEGACY_ID_RE.match(item_id)
    if match:
        return int(match.group(1))
    return 0


def _empty_manifest() -> dict[str, Any]:
    return {
        "last_task_id": 0,
        "last_story_id": 0,
        "last_epic_id": 0,
        "epics": {},
        "stories": {},
        "tasks": {},
    }


class Manifest:
    """Thread-safe manifest.yaml manager."""

    def __init__(self, tasks_dir: Path) -> None:
        self._path = tasks_dir / "manifest.yaml"
        self._lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        """Load manifest from disk. Creates empty manifest if file doesn't exist."""
        if not self._path.exists():
            return _empty_manifest()
        text = self._path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        if data is None:
            return _empty_manifest()
        # Ensure all expected keys exist
        for key, default in _empty_manifest().items():
            if key not in data:
                data[key] = default
        return data

    def save(self, data: dict[str, Any]) -> None:
        """Save manifest to disk atomically (write + rename)."""
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".yaml.tmp")
            tmp.write_text(
                yaml.dump(data, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
            tmp.replace(self._path)

    def next_task_id(self) -> str:
        """Generate a collision-resistant hash ID like ``T-a1b2c3d4``."""
        return _generate_hash_id("T")

    def next_story_id(self) -> str:
        """Generate a collision-resistant hash ID like ``S-a1b2c3d4``."""
        return _generate_hash_id("S")

    def next_epic_id(self) -> str:
        """Generate a collision-resistant hash ID like ``E-a1b2c3d4``."""
        return _generate_hash_id("E")

    def _write_unlocked(self, data: dict[str, Any]) -> None:
        """Write manifest without acquiring lock (caller holds it)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".yaml.tmp")
        tmp.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        tmp.replace(self._path)

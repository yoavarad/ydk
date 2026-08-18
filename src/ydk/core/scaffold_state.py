"""Track generated file hashes for idempotent ignition."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path


class ScaffoldState:
    """Track generated file hashes for idempotent ignition."""

    def __init__(self, state_path: Path) -> None:
        self._path = state_path  # .ydk/scaffold-state.yaml
        self._hashes: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        """Load stored hashes from disk."""
        if self._path.exists():
            data = yaml.safe_load(self._path.read_text())
            if isinstance(data, dict):
                self._hashes = data.get("hashes", {})

    def save(self) -> None:
        """Persist hashes to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(yaml.dump({"hashes": self._hashes}, default_flow_style=False))

    def is_modified(self, file_path: str, content: str) -> bool:
        """Check if content differs from stored hash. Returns True if new or changed."""
        new_hash = self._compute_hash(content)
        stored = self._hashes.get(file_path)
        return stored != new_hash

    def update(self, file_path: str, content: str) -> None:
        """Store the hash for a file."""
        self._hashes[file_path] = self._compute_hash(content)

    def is_developer_owned(self, file_path: str, project_root: Path) -> bool:
        """Check if file has been manually edited by the developer.

        A file is developer-owned if it exists on disk, has a stored hash
        (was previously generated), and the current content differs from the
        stored hash. New files (no stored hash) are not developer-owned.
        Non-existent files are not developer-owned.
        """
        full = project_root / file_path
        if not full.exists():
            return False
        stored = self._hashes.get(file_path)
        if stored is None:
            # Never tracked — not developer-owned (first generation)
            return False
        current_hash = self._compute_hash(full.read_text())
        return current_hash != stored

    @staticmethod
    def _compute_hash(content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()

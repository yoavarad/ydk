"""Content-hash-based verification result caching.

Caches verification plugin results keyed by plugin name + SHA256 hashes
of the files that were checked. A cache hit means the plugin produced
the same result last time it ran against identical file contents.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from typing import TYPE_CHECKING

from ydk.models.verification import CheckResult

if TYPE_CHECKING:
    from pathlib import Path


class VerificationCache:
    """Persistent, content-hash-based cache for verification results.

    Cache layout::

        .ydk/cache/verification/<plugin_name>/<content_hash>.json

    Where *content_hash* is a single SHA256 derived from the sorted
    mapping of ``{relative_path: file_sha256}``.
    """

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_cached(self, plugin_name: str, file_hashes: dict[str, str]) -> CheckResult | None:
        """Return a previously stored result if file hashes match, else ``None``."""
        path = self._entry_path(plugin_name, file_hashes)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return CheckResult(**data)
        except (json.JSONDecodeError, KeyError, TypeError):
            # Corrupt entry -- treat as miss.
            path.unlink(missing_ok=True)
            return None

    def store(self, plugin_name: str, file_hashes: dict[str, str], result: CheckResult) -> None:
        """Persist a verification result under the composite content hash."""
        path = self._entry_path(plugin_name, file_hashes)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.model_dump_json(indent=2))

    def invalidate(self, plugin_name: str | None = None) -> None:
        """Clear cached entries -- all plugins or a specific one."""
        target = self._dir / plugin_name if plugin_name is not None else self._dir
        if target.is_dir():
            shutil.rmtree(target)

    @staticmethod
    def compute_hash(files: list[Path]) -> dict[str, str]:
        """Return ``{relative_or_absolute_path: sha256_hex}`` for each file."""
        result: dict[str, str] = {}
        for f in sorted(files):
            if not f.is_file():
                continue
            h = hashlib.sha256(f.read_bytes()).hexdigest()
            result[str(f)] = h
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _composite_hash(self, file_hashes: dict[str, str]) -> str:
        """Derive a single SHA256 from sorted path:hash pairs."""
        h = hashlib.sha256()
        for key in sorted(file_hashes):
            h.update(f"{key}:{file_hashes[key]}".encode())
        return h.hexdigest()

    def _entry_path(self, plugin_name: str, file_hashes: dict[str, str]) -> Path:
        return self._dir / plugin_name / f"{self._composite_hash(file_hashes)}.json"

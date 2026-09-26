"""Shared resolver for task references given on the CLI.

Resolves batch placeholders (task/story/epic keys written by ``ydk task
create-batch`` to ``.ydk/batch-mapping.json``) and normalizes ``#N`` to ``N``.
Unmapped, non-numeric IDs are returned unchanged so backend-specific parsers
(e.g. the strict GitHub issue-number parser) can accept or reject them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_HASH_NUMBER = re.compile(r"#([0-9]+)")


def _normalize(ref: str) -> str:
    match = _HASH_NUMBER.fullmatch(ref)
    return match.group(1) if match else ref


def _load_mapping(mapping_file: Path) -> dict[str, str]:
    try:
        data = json.loads(mapping_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def resolve_task_ref(raw_id: str, mapping_file: Path | None = None) -> str:
    """Resolve a task reference via the batch mapping, then normalize ``#N``.

    Args:
        raw_id: ID as typed by the user (e.g. ``12``, ``#12``, ``T-001``, ``S-001``).
        mapping_file: Mapping path; defaults to ``.ydk/batch-mapping.json`` in cwd.

    Returns:
        The mapped value (or ``raw_id`` if unmapped) with ``#N`` normalized to ``N``.
    """
    ref = raw_id.strip()
    mapping = _load_mapping(mapping_file or Path(".ydk") / "batch-mapping.json")
    resolved = mapping.get(ref) or mapping.get(ref.upper()) or ref
    return _normalize(resolved)

"""Gate that flags finished epics with no retrospective recorded.

Used by ``ydk task start`` (refuse) and ``ydk doctor`` (warn). A retro is
considered recorded once ``ydk memory retrospective --epic <id>`` has
written ``.ydk/retros/<epic-id>.md`` -- true across every repository
backend, since that command always writes the file before marking the
backend-specific retro-done marker (see ``ydk.cli.memory_cmd.retrospective``).

Retro files carry YAML front-matter (``epic_id``, ``title``, ``url``) so a
reused epic number (repo recreated / issues migrated) is not mistaken for the
old epic. A retro matches an epic when ``epic_id`` and the whitespace-normalized
``title`` are equal and, if both sides have a url, the urls are equal. A legacy
``<epic-id>.md`` without front-matter matches that epic. When ``<epic-id>.md``
belongs to another epic, the retro is written to ``<epic-id>-<title-slug>.md``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import builtins

    from ydk.repositories.protocols import EpicRepository

_FINISHED_STATUSES = {"done", "closed"}


@runtime_checkable
class _ListsAll(Protocol):
    """Remote repo: ``.list(status=...)`` returns every epic (preferred -- has real details)."""

    def list(self, *, status: str) -> builtins.list: ...


@runtime_checkable
class _ListsEpics(Protocol):
    """Local/lifecycle-compatible repo: ``.list_epics(status=...)``."""

    def list_epics(self, status: str) -> builtins.list: ...


def _list_epics(epic_repo: EpicRepository) -> builtins.list:
    """List all epics across backends -- mirrors ``ydk.core.rollup._load_epics``.

    Not every backend satisfies both shapes (e.g. GitLab's epic repo only
    exposes ``.list()``, not the lifecycle ``.list_epics()`` alias), so probe
    structurally rather than assuming ``list_epics`` always exists.
    """
    if isinstance(epic_repo, _ListsAll):
        return epic_repo.list(status="all")
    if isinstance(epic_repo, _ListsEpics):
        return epic_repo.list_epics(status="all")
    return []


def _epic_key(epic: object) -> str:
    return str(getattr(epic, "id", "") or getattr(epic, "number", ""))


def lookup_epic(epic_repo: EpicRepository, epic_id: str) -> tuple[str, str] | None:
    """Return ``(title, url)`` for *epic_id* via the epic listing, or None if absent."""
    for epic in _list_epics(epic_repo):
        if _epic_key(epic) == epic_id:
            return str(getattr(epic, "title", "") or ""), str(getattr(epic, "url", "") or "")
    return None


def _norm(text: str) -> str:
    return " ".join(text.split())


def parse_frontmatter(text: str) -> dict[str, str] | None:
    """Parse the leading ``---`` YAML block of simple ``key: "value"`` lines; None if absent."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    data: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return data
        key, sep, value = line.partition(":")
        if not sep:
            continue
        value = value.strip()
        try:
            parsed = json.loads(value)
            value = parsed if isinstance(parsed, str) else value
        except ValueError:
            value = value.strip("'\"")
        data[key.strip()] = value
    return None


def render_frontmatter(epic_id: str, title: str, url: str) -> str:
    """Render the identity front-matter block for a retro file."""
    return f"---\nepic_id: {json.dumps(epic_id)}\ntitle: {json.dumps(_norm(title))}\nurl: {json.dumps(url)}\n---\n\n"


def retro_matches_epic(path: Path, epic_id: str, title: str, url: str) -> bool:
    """True when the retro file at *path* belongs to the given epic."""
    try:
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return False
    if fm is None:
        return path.name == f"{epic_id}.md"  # legacy file: matches by name only
    if fm.get("epic_id") != epic_id:
        return False
    if title and _norm(fm.get("title", "")) != _norm(title):  # empty title = epic unknown to backend
        return False
    file_url = fm.get("url", "")
    return not (file_url and url) or file_url == url


def _title_slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-")


def resolve_retro_path(retros_dir: Path, epic_id: str, title: str, url: str) -> Path:
    """Pick the file to write for this epic's retro without clobbering another epic's."""
    plain = retros_dir / f"{epic_id}.md"
    if not plain.exists() or retro_matches_epic(plain, epic_id, title, url):
        return plain
    base = f"{epic_id}-{_title_slug(title) or 'epic'}"
    n = 1
    while True:
        candidate = retros_dir / (f"{base}.md" if n == 1 else f"{base}-{n}.md")
        if not candidate.exists() or retro_matches_epic(candidate, epic_id, title, url):
            return candidate
        n += 1


@dataclass(frozen=True)
class MissingRetro:
    """A finished epic that has no retrospective recorded yet."""

    epic_id: str
    title: str


def find_epics_missing_retro(epic_repo: EpicRepository, retros_dir: Path = Path(".ydk/retros")) -> list[MissingRetro]:
    """Return finished (done/closed) epics with no matching retro in *retros_dir*."""
    finished = [e for e in _list_epics(epic_repo) if str(getattr(e, "status", "")) in _FINISHED_STATUSES]

    missing: list[MissingRetro] = []
    for epic in finished:
        epic_id = _epic_key(epic)
        title = str(epic.title)
        url = str(getattr(epic, "url", "") or "")
        candidates = [retros_dir / f"{epic_id}.md", *sorted(retros_dir.glob(f"{epic_id}-*.md"))]
        if not any(p.is_file() and retro_matches_epic(p, epic_id, title, url) for p in candidates):
            missing.append(MissingRetro(epic_id=epic_id, title=title))
    return missing

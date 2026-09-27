"""Gate that flags finished epics with no retrospective recorded.

Used by ``ydk task start`` (refuse) and ``ydk doctor`` (warn). A retro is
considered recorded once ``ydk memory retrospective --epic <id>`` has
written ``.ydk/retros/<epic-id>.md`` -- true across every repository
backend, since that command always writes the file before marking the
backend-specific retro-done marker (see ``ydk.cli.memory_cmd.retrospective``).
"""

from __future__ import annotations

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


@dataclass(frozen=True)
class MissingRetro:
    """A finished epic that has no retrospective recorded yet."""

    epic_id: str
    title: str


def find_epics_missing_retro(epic_repo: EpicRepository, retros_dir: Path = Path(".ydk/retros")) -> list[MissingRetro]:
    """Return finished (done/closed) epics with no ``<retros_dir>/<epic-id>.md``."""
    finished = [e for e in _list_epics(epic_repo) if str(getattr(e, "status", "")) in _FINISHED_STATUSES]

    missing: list[MissingRetro] = []
    for epic in finished:
        epic_id = str(getattr(epic, "id", "") or getattr(epic, "number", ""))
        if not (retros_dir / f"{epic_id}.md").exists():
            missing.append(MissingRetro(epic_id=epic_id, title=epic.title))
    return missing

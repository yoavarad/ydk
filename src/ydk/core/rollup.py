"""Roll a finished task up to its story and epic.

When a task becomes done, its story is marked done once every task in that
story is done, and its epic once every task under all of the epic's stories
is done. Works against any backend:

- local repositories expose ``list_tasks``/``get_task``, ``list_stories``,
  ``list_epics`` and ``update_status`` on stories and epics;
- remote (GitHub/GitLab) repositories expose ``list(status="all")`` returning
  details with ``story_id``/``epic_id``; stories and epics there are plain
  issues, so they are closed through the task repository's ``update_status``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import builtins

    from ydk.repositories.protocols import LifecycleTaskRepository

_DONE = {"done", "closed"}


@runtime_checkable
class _ListsAll(Protocol):
    """Remote repo: one call returns every issue of its kind with parent links."""

    def list(self, *, status: str) -> builtins.list: ...


@runtime_checkable
class _ListsStories(Protocol):
    def list_stories(self) -> builtins.list: ...


@runtime_checkable
class _ListsEpics(Protocol):
    def list_epics(self, status: str) -> builtins.list: ...


@runtime_checkable
class _SetsStatus(Protocol):
    def update_status(self, item_id: str, status: str) -> None: ...


@dataclass(frozen=True)
class _Node:
    id: str
    parent: str
    status: str
    title: str


def _norm(ref: object) -> str:
    """Normalize an id/ref so '#12', '12' and 12 compare equal."""
    return str(ref or "").strip().lstrip("#")


def _is_done(node: _Node) -> bool:
    return node.status in _DONE


def _node(item: object, parent: object = "") -> _Node:
    """Build a node from a task/story/epic detail or summary (local ids, or remote issue numbers)."""
    item_id = getattr(item, "id", "") or getattr(item, "number", "")
    return _Node(_norm(item_id), _norm(parent), str(getattr(item, "status", "")), str(getattr(item, "title", "")))


def _load_tasks(task_repo: LifecycleTaskRepository) -> list[_Node]:
    if isinstance(task_repo, _ListsAll):
        return [_node(d, d.story_id) for d in task_repo.list(status="all")]
    # Local summaries carry no story link; read it from each task file.
    return [_node(s, task_repo.get_task(s.id).story_id) for s in task_repo.list_tasks(state="all")]


def _load_stories(story_repo: object) -> list[_Node]:
    if isinstance(story_repo, _ListsAll):
        items = story_repo.list(status="all")
    elif isinstance(story_repo, _ListsStories):
        items = story_repo.list_stories()
    else:
        items = []
    return [_node(s, s.epic_id) for s in items]


def _load_epics(epic_repo: object) -> list[_Node]:
    if isinstance(epic_repo, _ListsAll):
        return [_node(e) for e in epic_repo.list(status="all")]
    if isinstance(epic_repo, _ListsEpics):
        return [_node(e) for e in epic_repo.list_epics(status="all")]
    return []


def _set_done(repo: object, task_repo: LifecycleTaskRepository, item_id: str) -> None:
    """Stories/epics own ``update_status`` locally; remotely they are issues closed via the task repo."""
    if isinstance(repo, _SetsStatus):
        repo.update_status(item_id, "done")
    else:
        task_repo.update_status(item_id, "done")


def rollup_task_done(
    task_id: str, task_repo: LifecycleTaskRepository, story_repo: object, epic_repo: object
) -> list[str]:
    """Close the story/epic of a just-finished task when it was their last open task.

    Call after *task_id* has been marked done. Returns human-readable lines
    (story/epic completion and the retrospective next step); an empty list
    means nothing changed (not the last task, no story, or already closed).
    """
    tasks = _load_tasks(task_repo)
    task = next((t for t in tasks if t.id == _norm(task_id)), None)
    if task is None or not task.parent:
        return []

    story_tasks = [t for t in tasks if t.parent == task.parent]
    if not all(_is_done(t) for t in story_tasks):
        return []

    stories = _load_stories(story_repo)
    story = next((s for s in stories if s.id == task.parent), None)
    if story is None:
        return []

    messages: list[str] = []
    if not _is_done(story):
        _set_done(story_repo, task_repo, story.id)
        n = len(story_tasks)
        messages.append(f'Story {story.id} "{story.title}" complete ({n}/{n} tasks)')

    if not story.parent:
        return messages
    siblings = [s for s in stories if s.parent == story.parent]
    epic_tasks = [t for t in tasks if t.parent in {s.id for s in siblings}]
    other_stories_done = all(_is_done(s) for s in siblings if s.id != story.id)
    if not (other_stories_done and all(_is_done(t) for t in epic_tasks)):
        return messages

    epic = next((e for e in _load_epics(epic_repo) if e.id == story.parent), None)
    if epic is None or _is_done(epic):
        return messages
    _set_done(epic_repo, task_repo, epic.id)
    n = len(epic_tasks)
    messages.append(f'Epic {epic.id} "{epic.title}" complete ({n}/{n} tasks)')
    messages.append(f"Next: ydk memory retrospective --epic {epic.id}")
    return messages

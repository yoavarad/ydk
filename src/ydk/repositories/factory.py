"""Repository factory -- returns the correct backend based on project.remote config.

Uses a single ``_get_repository`` helper to eliminate the duplicated
config-loading / if-elif-else pattern that was repeated for each entity type.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from ydk.core.config import load_config

if TYPE_CHECKING:
    from ydk.repositories.protocols import EpicRepository, LifecycleTaskRepository, StoryRepository

T = TypeVar("T")

# Registry mapping (remote, entity) -> (module_path, class_name)
_REGISTRY: dict[tuple[str, str], tuple[str, str]] = {
    ("github", "task"): ("ydk.repositories.github.tasks", "GitHubTaskRepository"),
    ("github", "epic"): ("ydk.repositories.github.epics", "GitHubEpicRepository"),
    ("github", "story"): ("ydk.repositories.github.stories", "GitHubStoryRepository"),
    ("gitlab", "task"): ("ydk.repositories.gitlab.tasks", "GitLabTaskRepository"),
    ("gitlab", "epic"): ("ydk.repositories.gitlab.epics", "GitLabEpicRepository"),
    ("gitlab", "story"): ("ydk.repositories.gitlab.stories", "GitLabStoryRepository"),
    ("local", "task"): ("ydk.repositories.local.tasks", "LocalTaskRepository"),
    ("local", "epic"): ("ydk.repositories.local.epics", "LocalEpicRepository"),
    ("local", "story"): ("ydk.repositories.local.stories", "LocalStoryRepository"),
}


def _get_repository(entity: str) -> object:
    """Resolve and instantiate a repository for *entity* based on config.

    ``entity`` must be one of ``"task"``, ``"epic"``, ``"story"``.
    Local repositories receive ``Path(".ydk")`` as their constructor argument.
    """
    config = load_config()
    remote = config.project.remote or "local"

    key = (remote, entity)
    if key not in _REGISTRY:
        # Fallback to local
        key = ("local", entity)

    module_path, class_name = _REGISTRY[key]

    # Lazy import to avoid pulling in all backends at startup
    import importlib

    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)

    if remote in ("local", "") or key[0] == "local":
        return cls(Path(".ydk"))
    return cls()


def get_task_repository() -> LifecycleTaskRepository:
    """Return a task repository based on project.remote config."""
    return _get_repository("task")  # ty: ignore[invalid-return-type]  # dynamic dispatch via importlib


def get_epic_repository() -> EpicRepository:
    """Return an epic repository based on project.remote config."""
    return _get_repository("epic")  # ty: ignore[invalid-return-type]  # dynamic dispatch via importlib


def get_story_repository() -> StoryRepository:
    """Return a story repository based on project.remote config."""
    return _get_repository("story")  # ty: ignore[invalid-return-type]  # dynamic dispatch via importlib

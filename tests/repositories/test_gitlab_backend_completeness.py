"""Contract tests — verify the GitLab backend implements all protocol methods."""

from __future__ import annotations

import inspect

import pytest

from ydk.repositories.gitlab.epics import GitLabEpicRepository
from ydk.repositories.gitlab.stories import GitLabStoryRepository
from ydk.repositories.gitlab.tasks import GitLabTaskRepository
from ydk.repositories.protocols import EpicRepository, LifecycleTaskRepository, StoryRepository, TaskRepository


def _public_methods(cls: type) -> set[str]:
    """Return the set of public method names on *cls*."""
    return {name for name, _ in inspect.getmembers(cls, predicate=inspect.isfunction) if not name.startswith("_")}


@pytest.mark.parametrize(
    ("protocol", "impl"),
    [
        (TaskRepository, GitLabTaskRepository),
        (LifecycleTaskRepository, GitLabTaskRepository),
        (StoryRepository, GitLabStoryRepository),
        (EpicRepository, GitLabEpicRepository),
    ],
)
def test_gitlab_repo_implements_protocol(protocol: type, impl: type) -> None:
    missing = _public_methods(protocol) - _public_methods(impl)
    assert missing == set(), f"{impl.__name__} missing {protocol.__name__} methods: {missing}"

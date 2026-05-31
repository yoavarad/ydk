"""Contract tests — verify GitHub backend implements all protocol methods."""

from __future__ import annotations

import inspect

from odk.repositories.github.epics import GitHubEpicRepository
from odk.repositories.github.stories import GitHubStoryRepository
from odk.repositories.github.tasks import GitHubTaskRepository
from odk.repositories.protocols import EpicRepository, LifecycleTaskRepository, StoryRepository


def _public_methods(cls: type) -> set[str]:
    """Return the set of public method names on *cls*."""
    return {name for name, _ in inspect.getmembers(cls, predicate=inspect.isfunction) if not name.startswith("_")}


class TestGitHubBackendCompleteness:
    """Every Protocol method must exist on the GitHub backend class."""

    def test_github_task_repo_implements_lifecycle_protocol(self) -> None:
        protocol_methods = _public_methods(LifecycleTaskRepository)
        github_methods = _public_methods(GitHubTaskRepository)
        missing = protocol_methods - github_methods
        assert missing == set(), f"GitHubTaskRepository missing protocol methods: {missing}"

    def test_github_story_repo_implements_story_protocol(self) -> None:
        protocol_methods = _public_methods(StoryRepository)
        github_methods = _public_methods(GitHubStoryRepository)
        missing = protocol_methods - github_methods
        assert missing == set(), f"GitHubStoryRepository missing protocol methods: {missing}"

    def test_github_epic_repo_implements_epic_protocol(self) -> None:
        protocol_methods = _public_methods(EpicRepository)
        github_methods = _public_methods(GitHubEpicRepository)
        missing = protocol_methods - github_methods
        assert missing == set(), f"GitHubEpicRepository missing protocol methods: {missing}"

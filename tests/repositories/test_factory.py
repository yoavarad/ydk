"""Tests for repository factory — ensures project.remote config routes to correct backend."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from ydk.core.config import DEFAULT_CONFIG

if TYPE_CHECKING:
    from pathlib import Path


def _write_config(tmp_path: Path, remote: str) -> None:
    """Write a config file with the specified remote value."""
    config = {**DEFAULT_CONFIG, "project": {**DEFAULT_CONFIG["project"], "remote": remote}}
    config_dir = tmp_path / ".ydk"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(yaml.dump(config, default_flow_style=False))


def test_factory_returns_local_task_repo(tmp_path: Path, monkeypatch: object) -> None:
    """get_task_repository returns LocalTaskRepository when remote is 'local'."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _write_config(tmp_path, "local")

    from ydk.repositories.factory import get_task_repository
    from ydk.repositories.local.tasks import LocalTaskRepository

    repo = get_task_repository()
    assert isinstance(repo, LocalTaskRepository)


def test_factory_returns_github_task_repo(tmp_path: Path, monkeypatch: object) -> None:
    """get_task_repository returns GitHubTaskRepository when remote is 'github'."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _write_config(tmp_path, "github")

    from ydk.repositories.factory import get_task_repository
    from ydk.repositories.github.tasks import GitHubTaskRepository

    repo = get_task_repository()
    assert isinstance(repo, GitHubTaskRepository)


def test_factory_returns_gitlab_task_repo(tmp_path: Path, monkeypatch: object) -> None:
    """get_task_repository returns GitLabTaskRepository when remote is 'gitlab'."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _write_config(tmp_path, "gitlab")

    from ydk.repositories.factory import get_task_repository
    from ydk.repositories.gitlab.tasks import GitLabTaskRepository

    repo = get_task_repository()
    assert isinstance(repo, GitLabTaskRepository)


def test_factory_returns_github_epic_repo(tmp_path: Path, monkeypatch: object) -> None:
    """get_epic_repository returns GitHubEpicRepository when remote is 'github'."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _write_config(tmp_path, "github")

    from ydk.repositories.factory import get_epic_repository
    from ydk.repositories.github.epics import GitHubEpicRepository

    repo = get_epic_repository()
    assert isinstance(repo, GitHubEpicRepository)


def test_factory_returns_github_story_repo(tmp_path: Path, monkeypatch: object) -> None:
    """get_story_repository returns GitHubStoryRepository when remote is 'github'."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _write_config(tmp_path, "github")

    from ydk.repositories.factory import get_story_repository
    from ydk.repositories.github.stories import GitHubStoryRepository

    repo = get_story_repository()
    assert isinstance(repo, GitHubStoryRepository)


def test_factory_returns_local_repos_by_default(tmp_path: Path, monkeypatch: object) -> None:
    """Factory returns local repos when no config exists (default behavior)."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    # No config file — load_config returns defaults with remote='local'

    from ydk.repositories.factory import get_epic_repository, get_story_repository, get_task_repository
    from ydk.repositories.local.epics import LocalEpicRepository
    from ydk.repositories.local.stories import LocalStoryRepository
    from ydk.repositories.local.tasks import LocalTaskRepository

    assert isinstance(get_task_repository(), LocalTaskRepository)
    assert isinstance(get_epic_repository(), LocalEpicRepository)
    assert isinstance(get_story_repository(), LocalStoryRepository)

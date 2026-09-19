"""Regression tests: issue list calls must not silently truncate at the CLI default page size."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from ydk.repositories.github._helpers import GH_LIST_LIMIT
from ydk.repositories.github.epics import GitHubEpicRepository
from ydk.repositories.github.stories import GitHubStoryRepository
from ydk.repositories.github.tasks import GitHubTaskRepository
from ydk.repositories.gitlab.epics import GitLabEpicRepository
from ydk.repositories.gitlab.stories import GitLabStoryRepository
from ydk.repositories.gitlab.tasks import GitLabTaskRepository


def _fake(stdout: str = "[]", returncode: int = 0) -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr="")


def _gh_items(count: int, start: int = 1, state: str = "OPEN") -> list[dict]:
    return [
        {"number": n, "title": f"T{n}", "state": state, "labels": [], "body": "", "url": ""}
        for n in range(start, start + count)
    ]


def _glab_items(count: int, start: int = 1) -> list[dict]:
    return [
        {"iid": n, "title": f"T{n}", "state": "opened", "labels": [], "description": ""}
        for n in range(start, start + count)
    ]


def _dependent_on_50() -> dict:
    return {
        "number": 53,
        "title": "Dependent",
        "state": "OPEN",
        "labels": [],
        "body": "**Dependencies**: 50",
        "url": "",
    }


class TestGitHubListLimit:
    @pytest.mark.parametrize(
        ("module", "repo_cls"),
        [
            ("tasks", GitHubTaskRepository),
            ("epics", GitHubEpicRepository),
            ("stories", GitHubStoryRepository),
        ],
    )
    def test_list_passes_explicit_limit(self, module: str, repo_cls: type) -> None:
        with patch(f"ydk.repositories.github.{module}.run_gh", return_value=_fake()) as mock_run:
            repo_cls().list()
        cmd = mock_run.call_args[0][0]
        assert "--limit" in cmd
        assert int(cmd[cmd.index("--limit") + 1]) == GH_LIST_LIMIT
        assert GH_LIST_LIMIT >= 1000

    def test_task_list_returns_more_than_default_page(self) -> None:
        fake = _fake(json.dumps(_gh_items(45)))
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake):
            assert len(GitHubTaskRepository().list(status="all")) == 45


class TestGitHubListTasksAllState:
    def test_closed_dependency_counts_as_met_when_state_all(self) -> None:
        items = [*_gh_items(1, start=50, state="CLOSED"), _dependent_on_50()]
        fake = _fake(json.dumps(items))
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake):
            summaries = GitHubTaskRepository().list_tasks(state="all")
        by_id = {s.id: s for s in summaries}
        assert by_id["53"].dependencies_met is True

    def test_open_dependency_not_met_when_state_all(self) -> None:
        items = [*_gh_items(1, start=50, state="OPEN"), _dependent_on_50()]
        fake = _fake(json.dumps(items))
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake):
            summaries = GitHubTaskRepository().list_tasks(state="all")
        by_id = {s.id: s for s in summaries}
        assert by_id["53"].dependencies_met is False


class TestGitLabListPagination:
    @pytest.mark.parametrize(
        ("module", "repo_cls"),
        [
            ("tasks", GitLabTaskRepository),
            ("epics", GitLabEpicRepository),
            ("stories", GitLabStoryRepository),
        ],
    )
    def test_list_requests_max_page_size(self, module: str, repo_cls: type) -> None:
        with patch(f"ydk.repositories.gitlab.{module}.run_glab", return_value=_fake()) as mock_run:
            repo_cls().list()
        cmd = mock_run.call_args[0][0]
        assert cmd[cmd.index("--per-page") + 1] == "100"
        assert cmd[cmd.index("--page") + 1] == "1"

    @pytest.mark.parametrize(
        ("module", "repo_cls"),
        [
            ("tasks", GitLabTaskRepository),
            ("epics", GitLabEpicRepository),
            ("stories", GitLabStoryRepository),
        ],
    )
    def test_list_follows_pages_until_short_page(self, module: str, repo_cls: type) -> None:
        pages = [_fake(json.dumps(_glab_items(100))), _fake(json.dumps(_glab_items(7, start=101)))]
        with patch(f"ydk.repositories.gitlab.{module}.run_glab", side_effect=pages) as mock_run:
            result = repo_cls().list()
        assert len(result) == 107
        assert mock_run.call_count == 2
        second_cmd = mock_run.call_args_list[1][0][0]
        assert second_cmd[second_cmd.index("--page") + 1] == "2"

    def test_failure_on_later_page_returns_empty(self) -> None:
        pages = [_fake(json.dumps(_glab_items(100))), _fake(returncode=1)]
        with patch("ydk.repositories.gitlab.tasks.run_glab", side_effect=pages):
            assert GitLabTaskRepository().list() == []

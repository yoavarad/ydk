"""Tests for GitLabTaskRepository -- all glab CLI calls are mocked."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ydk.models.pm import AcceptanceCriterion, TaskCreate, TaskStatus
from ydk.repositories.gitlab.tasks import GitLabTaskRepository

# -- Helpers ---------------------------------------------------------------


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _make_repo() -> tuple[GitLabTaskRepository, MagicMock]:
    repo = GitLabTaskRepository()
    mock_run = MagicMock()
    return repo, mock_run


def _sample_create() -> TaskCreate:
    return TaskCreate(
        title="Implement order validation",
        story_id="S-001",
        spec_refs=["orders.md#entities"],
        dependencies=["T-001"],
        test_strategy="Unit tests",
        description="Validate all order fields",
        acceptance_criteria=[
            AcceptanceCriterion(text="Required fields checked", done=False),
        ],
        labels=["task", "sprint-1"],
        milestone="Sprint 1",
    )


def _sample_issue_json(
    iid: int = 42,
    title: str = "Implement order validation",
    state: str = "opened",
) -> dict:
    return {
        "iid": iid,
        "title": title,
        "state": state,
        "description": (
            "**Story**: S-001\n"
            "**Spec refs**: orders.md#entities\n"
            "**Dependencies**: T-001\n"
            "**Test strategy**: Unit tests\n"
            "\n"
            "### Description\n"
            "Validate all order fields\n"
            "\n"
            "### Acceptance Criteria\n"
            "- [ ] Required fields checked"
        ),
        "labels": [{"name": "task"}, {"name": "sprint-1"}],
        "web_url": "https://gitlab.com/owner/repo/-/issues/42",
    }


# -- create ----------------------------------------------------------------


class TestCreate:
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_create_success(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed(stdout="Creating issue...\nhttps://gitlab.com/owner/repo/-/issues/42")

        task = _sample_create()
        detail = repo.create(task)

        assert detail.number == 42
        assert detail.title == "Implement order validation"
        assert detail.story_id == "S-001"
        assert detail.status == TaskStatus.OPEN
        assert detail.url == "https://gitlab.com/owner/repo/-/issues/42"

        # Verify CLI args
        call_args = mock_run.call_args[0][0]
        assert call_args[0:3] == ["glab", "issue", "create"]
        assert "--title" in call_args
        assert "--label" in call_args
        assert "--milestone" in call_args

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_create_failure_raises(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed(returncode=1, stderr="auth error")

        with pytest.raises(RuntimeError, match="glab issue create failed"):
            repo.create(_sample_create())

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_create_without_optional_fields(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed(stdout="https://gitlab.com/owner/repo/-/issues/99")

        task = TaskCreate(title="Bare minimum task")
        detail = repo.create(task)

        assert detail.number == 99
        assert detail.labels == []
        call_args = mock_run.call_args[0][0]
        assert "--label" not in call_args
        assert "--milestone" not in call_args


# -- get -------------------------------------------------------------------


class TestGet:
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_get_success(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed(stdout=json.dumps(_sample_issue_json()))

        detail = repo.get(42)

        assert detail.number == 42
        assert detail.story_id == "S-001"
        assert detail.spec_refs == ["orders.md#entities"]
        assert detail.dependencies == ["T-001"]
        assert len(detail.acceptance_criteria) == 1
        assert detail.acceptance_criteria[0].text == "Required fields checked"

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_get_failure_raises(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed(returncode=1, stderr="not found")

        with pytest.raises(RuntimeError, match="glab issue view failed"):
            repo.get(999)

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_get_closed_issue(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        issue = _sample_issue_json(state="closed")
        mock_run.return_value = _completed(stdout=json.dumps(issue))

        detail = repo.get(42)
        assert detail.status == TaskStatus.DONE

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_get_with_string_labels(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        issue = _sample_issue_json()
        issue["labels"] = ["task", "sprint-1"]  # plain strings, not dicts
        mock_run.return_value = _completed(stdout=json.dumps(issue))

        detail = repo.get(42)
        assert detail.labels == ["task", "sprint-1"]


# -- list ------------------------------------------------------------------


class TestList:
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_list_success(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed(stdout=json.dumps([_sample_issue_json()]))

        details = repo.list()

        assert len(details) == 1
        assert details[0].number == 42

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_list_with_filters(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed(stdout=json.dumps([]))

        repo.list(milestone="Sprint 1", labels=["task"], status="open")

        call_args = mock_run.call_args[0][0]
        assert "--milestone" in call_args
        assert "--label" in call_args
        assert "--state" in call_args
        idx = call_args.index("--state")
        assert call_args[idx + 1] == "opened"  # 'open' -> 'opened'

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_list_returns_empty_on_failure(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed(returncode=1, stderr="error")

        assert repo.list() == []

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_list_returns_empty_on_bad_json(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed(stdout="not json")

        assert repo.list() == []


# -- update_status ---------------------------------------------------------


class TestUpdateStatus:
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_close_issue(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed()

        repo.update_status(42, "done")

        call_args = mock_run.call_args[0][0]
        assert call_args == ["glab", "issue", "close", "42"]

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_reopen_issue(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed()

        repo.update_status(42, "open")

        call_args = mock_run.call_args[0][0]
        assert call_args == ["glab", "issue", "reopen", "42"]

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_label_based_status(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed()

        repo.update_status(42, "in_progress")

        call_args = mock_run.call_args[0][0]
        assert "status:in_progress" in call_args

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_update_failure_raises(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed(returncode=1, stderr="forbidden")

        with pytest.raises(RuntimeError, match="glab issue update failed"):
            repo.update_status(42, "blocked")


# -- add_comment -----------------------------------------------------------


class TestAddComment:
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_add_comment_success(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed()

        repo.add_comment(42, "Looking good!")

        call_args = mock_run.call_args[0][0]
        assert call_args == ["glab", "issue", "note", "42", "--message", "Looking good!"]

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_add_comment_failure_raises(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed(returncode=1, stderr="not found")

        with pytest.raises(RuntimeError, match="glab issue note failed"):
            repo.add_comment(999, "test")

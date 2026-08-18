"""Tests for GitHubTaskRepository — all subprocess calls mocked."""

import json
from unittest.mock import MagicMock, patch

import pytest

from ydk.models.pm import AcceptanceCriterion, TaskCreate, TaskStatus
from ydk.repositories.github.tasks import GitHubTaskRepository


def _fake_run(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    def test_creates_issue_and_returns_detail(self) -> None:
        repo = GitHubTaskRepository()
        task = TaskCreate(
            title="Validate orders",
            story_id="S-001",
            spec_refs=["orders.md#entities"],
            dependencies=["T-001"],
            test_strategy="Unit tests",
            description="Implement validation",
            acceptance_criteria=[AcceptanceCriterion(text="It works")],
        )
        fake = _fake_run(stdout="https://github.com/org/repo/issues/42\n")
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake) as mock_run:
            detail = repo.create(task)

        assert detail.number == 42
        assert detail.title == "Validate orders"
        # GitHub renderer converts "S-001" -> "#1" in the issue body
        assert detail.story_id == "#1"
        assert detail.status == TaskStatus.OPEN
        assert detail.url == "https://github.com/org/repo/issues/42"

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "gh"
        assert "--title" in cmd
        assert "--body" in cmd
        assert "--label" in cmd
        assert "task" in cmd

    def test_with_extra_labels_and_milestone(self) -> None:
        repo = GitHubTaskRepository()
        task = TaskCreate(title="T", labels=["p1", "backend"], milestone="v1.0")
        fake = _fake_run(stdout="https://github.com/org/repo/issues/10\n")
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake) as mock_run:
            detail = repo.create(task)

        assert detail.number == 10
        cmd = mock_run.call_args[0][0]
        assert "--milestone" in cmd
        assert "v1.0" in cmd
        # Should have task label + p1 + backend
        label_indices = [i for i, v in enumerate(cmd) if v == "--label"]
        assert len(label_indices) == 3  # task, p1, backend

    def test_raises_on_failure(self) -> None:
        repo = GitHubTaskRepository()
        task = TaskCreate(title="T")
        fake = _fake_run(returncode=1, stderr="auth required")
        with (
            patch("ydk.repositories.github.tasks.run_gh", return_value=fake),
            pytest.raises(RuntimeError, match="auth"),
        ):
            repo.create(task)


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestGet:
    def test_fetches_and_parses_issue(self) -> None:
        repo = GitHubTaskRepository()
        issue_json = json.dumps(
            {
                "number": 42,
                "title": "Validate orders",
                "state": "OPEN",
                "labels": [{"name": "task"}, {"name": "p1"}],
                "body": (
                    "**Story**: S-001\n**Spec refs**: orders.md#entities\n\n"
                    "### Description\nValidation logic\n\n"
                    "### Acceptance Criteria\n- [ ] It works"
                ),
                "url": "https://github.com/org/repo/issues/42",
            }
        )
        fake = _fake_run(stdout=issue_json)
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake) as mock_run:
            detail = repo.get(42)

        assert detail.number == 42
        assert detail.story_id == "S-001"
        assert detail.spec_refs == ["orders.md#entities"]
        assert "Validation logic" in detail.description
        assert len(detail.acceptance_criteria) == 1
        assert detail.labels == ["task", "p1"]
        assert detail.status == TaskStatus.OPEN

        cmd = mock_run.call_args[0][0]
        assert "42" in cmd
        assert "--json" in cmd

    def test_raises_on_not_found(self) -> None:
        repo = GitHubTaskRepository()
        fake = _fake_run(returncode=1, stderr="not found")
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake), pytest.raises(RuntimeError):
            repo.get(999)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestList:
    def test_returns_parsed_list(self) -> None:
        repo = GitHubTaskRepository()
        items = [
            {
                "number": 1,
                "title": "First",
                "state": "OPEN",
                "labels": [{"name": "task"}],
                "body": "**Story**: S-001\n\n### Description\nFirst task",
                "url": "https://github.com/org/repo/issues/1",
            },
            {
                "number": 2,
                "title": "Second",
                "state": "CLOSED",
                "labels": [{"name": "task"}],
                "body": "",
                "url": "https://github.com/org/repo/issues/2",
            },
        ]
        fake = _fake_run(stdout=json.dumps(items))
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake):
            result = repo.list()

        assert len(result) == 2
        assert result[0].number == 1
        assert result[0].status == TaskStatus.OPEN
        assert result[1].status == TaskStatus.DONE

    def test_with_filters(self) -> None:
        repo = GitHubTaskRepository()
        fake = _fake_run(stdout="[]")
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake) as mock_run:
            repo.list(milestone="v1.0", labels=["p1"], status="closed")

        cmd = mock_run.call_args[0][0]
        assert "--milestone" in cmd
        assert "v1.0" in cmd
        assert "--state" in cmd
        assert "closed" in cmd
        # Should have task label + p1
        label_indices = [i for i, v in enumerate(cmd) if v == "--label"]
        assert len(label_indices) == 2

    def test_returns_empty_on_failure(self) -> None:
        repo = GitHubTaskRepository()
        fake = _fake_run(returncode=1, stderr="network error")
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake):
            assert repo.list() == []


# ---------------------------------------------------------------------------
# update_status
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    def test_close_issue(self) -> None:
        repo = GitHubTaskRepository()
        fake = _fake_run()
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake) as mock_run:
            repo.update_status(42, "closed")
        cmd = mock_run.call_args[0][0]
        assert "close" in cmd
        assert "42" in [str(c) for c in cmd]

    def test_done_also_closes(self) -> None:
        repo = GitHubTaskRepository()
        fake = _fake_run()
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake) as mock_run:
            repo.update_status(42, "done")
        cmd = mock_run.call_args[0][0]
        assert "close" in cmd

    def test_reopen_issue(self) -> None:
        repo = GitHubTaskRepository()
        fake = _fake_run()
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake) as mock_run:
            repo.update_status(42, "open")
        cmd = mock_run.call_args[0][0]
        assert "reopen" in cmd

    def test_add_label_for_other_statuses(self) -> None:
        repo = GitHubTaskRepository()
        fake = _fake_run()
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake) as mock_run:
            repo.update_status(42, "in-progress")
        cmd = mock_run.call_args[0][0]
        assert "--add-label" in cmd
        assert "in-progress" in cmd

    def test_raises_on_failure(self) -> None:
        repo = GitHubTaskRepository()
        fake = _fake_run(returncode=1, stderr="error")
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake), pytest.raises(RuntimeError):
            repo.update_status(42, "closed")


# ---------------------------------------------------------------------------
# add_comment
# ---------------------------------------------------------------------------


class TestAddComment:
    def test_adds_comment(self) -> None:
        repo = GitHubTaskRepository()
        fake = _fake_run()
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake) as mock_run:
            repo.add_comment(42, "LGTM!")
        cmd = mock_run.call_args[0][0]
        assert "comment" in cmd
        assert "42" in [str(c) for c in cmd]
        assert "--body" in cmd
        assert "LGTM!" in cmd

    def test_raises_on_failure(self) -> None:
        repo = GitHubTaskRepository()
        fake = _fake_run(returncode=1, stderr="error")
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake), pytest.raises(RuntimeError):
            repo.add_comment(42, "text")

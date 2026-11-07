"""Tests for GitLabTaskRepository -- all glab CLI calls are mocked."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from ydk.models.pm import AcceptanceCriterion, TaskCreate, TaskStatus
from ydk.repositories.gitlab.tasks import GitLabTaskRepository

if TYPE_CHECKING:
    from collections.abc import Callable

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
        assert detail.labels == ["task"]
        call_args = mock_run.call_args[0][0]
        assert call_args[call_args.index("--label") + 1] == "task"
        assert "--milestone" not in call_args

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_create_writes_task_label_once(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(stdout="https://gitlab.com/owner/repo/-/issues/42")

        detail = GitLabTaskRepository().create(_sample_create())

        call_args = mock_run.call_args[0][0]
        assert call_args[call_args.index("--label") + 1] == "task,sprint-1"
        assert detail.labels == ["task", "sprint-1"]

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_create_task_creates_labelled_issue(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(stdout="https://gitlab.com/owner/repo/-/issues/7")

        detail = GitLabTaskRepository().create_task(TaskCreate(title="Quick fix", labels=["in-progress"]))

        assert (detail.number, detail.title) == (7, "Quick fix")
        call_args = mock_run.call_args[0][0]
        assert call_args[0:3] == ["glab", "issue", "create"]
        assert call_args[call_args.index("--label") + 1] == "task,in-progress"


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
        assert "--state" not in call_args
        assert "--closed" not in call_args
        assert "--all" not in call_args

    @pytest.mark.parametrize(
        ("status", "flags"),
        [("open", []), ("closed", ["--closed"]), ("done", ["--closed"]), ("all", ["--all"])],
    )
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_list_state_flags(self, mock_run: MagicMock, status: str, flags: list[str]) -> None:
        mock_run.return_value = _completed(stdout=json.dumps([]))

        GitLabTaskRepository().list(status=status)

        call_args = mock_run.call_args[0][0]
        assert "--state" not in call_args
        for flag in ("--closed", "--all"):
            assert (flag in call_args) == (flag in flags)

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_list_raises_on_failure(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed(returncode=1, stderr="unknown flag: --state")

        with pytest.raises(RuntimeError, match="unknown flag"):
            repo.list()

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_list_raises_on_bad_json(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed(stdout="not json")

        with pytest.raises(RuntimeError):
            repo.list()


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
    def test_close_removes_stale_status_labels_before_closing(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed()

        repo.update_status(42, "done")

        calls = [c[0][0] for c in mock_run.call_args_list]
        assert calls == [
            ["glab", "issue", "update", "42", "--unlabel", "status:in-review,status:in-progress"],
            ["glab", "issue", "close", "42"],
        ]

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_close_ignores_unlabel_failure(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.side_effect = [_completed(returncode=1, stderr="no such label"), _completed()]

        repo.update_status(42, "done")

        assert mock_run.call_args[0][0] == ["glab", "issue", "close", "42"]

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


# -- list_tasks / list_ready -----------------------------------------------


def _issue(iid: int, deps: str = "", labels: list[str] | None = None, state: str = "opened") -> dict:
    body = f"**Dependencies**: {deps}\n\n### Description\nx\n" if deps else "### Description\nx\n"
    return {
        "iid": iid,
        "title": f"Task {iid}",
        "state": state,
        "description": body,
        "labels": [{"name": n} for n in (labels or ["task"])],
        "web_url": f"https://gitlab.com/owner/repo/-/issues/{iid}",
    }


def _fake_glab(
    open_issues: list[dict], closed_issues: list[dict]
) -> Callable[[list[str]], subprocess.CompletedProcess[str]]:
    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if "--closed" in cmd:
            issues = closed_issues
        elif "--all" in cmd:
            issues = open_issues + closed_issues
        else:
            issues = open_issues
        if "--label" in cmd:
            wanted = set(cmd[cmd.index("--label") + 1].split(","))
            issues = [i for i in issues if wanted <= {lbl["name"] for lbl in i["labels"]}]
        return _completed(stdout=json.dumps(issues))

    return run


class TestListTasks:
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_returns_summaries_with_dependency_status(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _fake_glab(
            [_issue(5, deps="#3"), _issue(6, deps="#4"), _issue(7)],
            [_issue(3, state="closed")],
        )

        summaries = GitLabTaskRepository().list_tasks()

        by_id = {s.id: s for s in summaries}
        assert set(by_id) == {"5", "6", "7"}
        assert by_id["5"].dependencies_met is True
        assert by_id["6"].dependencies_met is False
        assert by_id["7"].dependencies_met is True
        assert by_id["5"].status == TaskStatus.OPEN

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_excludes_epic_and_story_issues(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _fake_glab(
            [_issue(1, labels=["kind:epic"]), _issue(2, labels=["kind:story"]), _issue(5)],
            [],
        )

        assert [s.id for s in GitLabTaskRepository().list_tasks()] == ["5"]

    @pytest.mark.parametrize("state", ["open", "closed"])
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_filters_listing_by_task_label(self, mock_run: MagicMock, state: str) -> None:
        mock_run.side_effect = _fake_glab(
            [_issue(5), _issue(6, labels=["bug"])], [_issue(5), _issue(6, labels=["bug"])]
        )

        assert [s.id for s in GitLabTaskRepository().list_tasks(state=state)] == ["5"]
        listing = mock_run.call_args_list[0].args[0]
        assert listing[listing.index("--label") + 1] == "task"

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_state_all_excludes_unlabelled_issues(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _fake_glab([_issue(5), _issue(6, labels=["bug"])], [])

        assert [s.id for s in GitLabTaskRepository().list_tasks(state="all")] == ["5"]

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_state_all_uses_closed_from_same_listing(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _fake_glab([_issue(5, deps="#3")], [_issue(3, state="closed")])

        summaries = GitLabTaskRepository().list_tasks(state="all")

        by_id = {s.id: s for s in summaries}
        assert by_id["3"].status == TaskStatus.DONE
        assert by_id["5"].dependencies_met is True
        assert all("--all" in c.args[0] for c in mock_run.call_args_list)

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_unresolvable_dependency_is_unmet(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _fake_glab([_issue(5, deps="T-5e9dbd18")], [])

        assert GitLabTaskRepository().list_tasks()[0].dependencies_met is False

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_state_all_counts_closed_story_as_done_dependency(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _fake_glab([_issue(5, deps="#2")], [_issue(2, labels=["kind:story"], state="closed")])

        summaries = GitLabTaskRepository().list_tasks(state="all")

        assert [(s.id, s.dependencies_met) for s in summaries] == [("5", True)]

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_state_closed_lists_closed_tasks(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _fake_glab(
            [_issue(5)], [_issue(3, state="closed"), _issue(4, deps="#3", state="closed")]
        )

        summaries = GitLabTaskRepository().list_tasks(state="closed")

        assert [(s.id, s.status, s.dependencies_met) for s in summaries] == [
            ("3", TaskStatus.DONE, True),
            ("4", TaskStatus.DONE, True),
        ]


class TestListReady:
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_returns_open_unblocked_tasks_ranked_by_dependents(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _fake_glab(
            [
                _issue(5, deps="#3"),
                _issue(6, deps="#4"),
                _issue(7),
                _issue(8, deps="#7"),
                _issue(10, labels=["kind:epic"]),
            ],
            [_issue(3, state="closed")],
        )

        ready = GitLabTaskRepository().list_ready()

        assert [t.id for t in ready] == ["7", "5"]
        assert ready[0].dependents_count == 1
        assert all(t.dependencies_met for t in ready)

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_empty_project_returns_empty(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _fake_glab([], [])

        assert GitLabTaskRepository().list_ready() == []

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_filters_open_listing_by_task_label(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _fake_glab([_issue(5), _issue(6, labels=["bug"])], [])

        assert [t.id for t in GitLabTaskRepository().list_ready()] == ["5"]
        listing = mock_run.call_args_list[0].args[0]
        assert listing[listing.index("--label") + 1] == "task"


class TestListEmptyStdout:
    @pytest.mark.parametrize("stdout", ["", "   \n"])
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_empty_stdout_with_success_is_empty_list(self, mock_run: MagicMock, stdout: str) -> None:
        mock_run.return_value = _completed(stdout=stdout)

        assert GitLabTaskRepository().list() == []
        assert GitLabTaskRepository().list_tasks() == []

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_empty_second_page_stops_paging(self, mock_run: MagicMock) -> None:
        full_page = [_issue(i) for i in range(1, 101)]
        mock_run.side_effect = [_completed(stdout=json.dumps(full_page)), _completed(stdout="")]

        assert len(GitLabTaskRepository().list()) == 100
        assert mock_run.call_count == 2

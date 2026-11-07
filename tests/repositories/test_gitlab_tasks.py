"""Tests for GitLabTaskRepository -- all glab CLI calls are mocked."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from ydk.models.gate import Gate, GateStatus, GateType
from ydk.models.pm import AcceptanceCriterion, Dependency, TaskCreate, TaskStatus
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
            [
                "glab",
                "issue",
                "update",
                "42",
                "--unlabel",
                "status:in-review,status:in-progress,status:blocked-by-code,status:blocked-by-decision",
            ],
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


# -- get_task --------------------------------------------------------------


class TestGetTask:
    @pytest.mark.parametrize("task_id", ["42", "#42", " 42 "])
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_get_task_accepts_string_ids(self, mock_run: MagicMock, task_id: str) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed(stdout=json.dumps(_sample_issue_json(iid=42)))

        detail = repo.get_task(task_id)

        assert detail.number == 42
        assert mock_run.call_args[0][0][:4] == ["glab", "issue", "view", "42"]

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_get_task_failure_raises(self, mock_run: MagicMock) -> None:
        repo = GitLabTaskRepository()
        mock_run.return_value = _completed(returncode=1, stderr="404 not found")

        with pytest.raises(RuntimeError, match="glab issue view failed"):
            repo.get_task("7")

    @pytest.mark.parametrize("task_id", ["T-001", "E-042", "abc", "#", "", "-5"])
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_get_task_rejects_non_numeric_ids(self, mock_run: MagicMock, task_id: str) -> None:
        repo = GitLabTaskRepository()

        with pytest.raises(ValueError, match="not a GitLab issue number"):
            repo.get_task(task_id)

        mock_run.assert_not_called()


# -- add_label / remove_label (#703) ----------------------------------------


class TestAddLabel:
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_adds_plain_label(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed()

        GitLabTaskRepository().add_label("#42", "archived")

        mock_run.assert_called_once_with(["glab", "issue", "update", "42", "--label", "archived"])

    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("in-progress", "status:in-progress"),
            ("in-review", "status:in-review"),
            ("blocked-by-code", "status:blocked-by-code"),
            ("blocked-by-decision", "status:blocked-by-decision"),
            ("status:blocked", "status:blocked"),
        ],
    )
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_status_labels_use_status_prefix(self, mock_run: MagicMock, label: str, expected: str) -> None:
        mock_run.return_value = _completed()

        GitLabTaskRepository().add_label("42", label)

        mock_run.assert_called_once_with(["glab", "issue", "update", "42", "--label", expected])

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_failure_raises(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="boom")

        with pytest.raises(RuntimeError, match="boom"):
            GitLabTaskRepository().add_label("42", "archived")


class TestRemoveLabel:
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_unlabels_with_status_prefix(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed()

        GitLabTaskRepository().remove_label("42", "blocked-by-code")

        mock_run.assert_called_once_with(["glab", "issue", "update", "42", "--unlabel", "status:blocked-by-code"])

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_failure_is_ignored(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="label not found")

        GitLabTaskRepository().remove_label("42", "in-progress")  # must not raise


# -- update_gates (#703) -----------------------------------------------------


def _gate(status: GateStatus = GateStatus.PENDING) -> Gate:
    return Gate(id="G-1", type=GateType.HUMAN, description="Sign-off", status=status)


def _view_and_update(description: str) -> tuple[MagicMock, list[list[str]]]:
    calls: list[list[str]] = []

    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd[2] == "view":
            return _completed(stdout=json.dumps({"iid": 42, "description": description}))
        return _completed()

    return MagicMock(side_effect=run), calls


def _written_description(calls: list[list[str]]) -> str:
    update = calls[-1]
    assert update[:4] == ["glab", "issue", "update", "42"]
    return update[update.index("--description") + 1]


class TestUpdateGates:
    def test_appends_gates_section(self) -> None:
        mock_run, calls = _view_and_update("### Description\nDo it")
        with patch("ydk.repositories.gitlab.tasks.run_glab", mock_run):
            GitLabTaskRepository().update_gates("42", [_gate()])

        assert calls[0][:4] == ["glab", "issue", "view", "42"]
        assert _written_description(calls) == (
            "### Description\nDo it\n\n### Gates\n- **G-1** (human): Sign-off [pending]"
        )

    def test_replaces_existing_gates_section(self) -> None:
        body = "### Gates\n- **G-1** (human): Sign-off [pending]\n### Acceptance Criteria\n- [ ] x"
        mock_run, calls = _view_and_update(body)
        with patch("ydk.repositories.gitlab.tasks.run_glab", mock_run):
            GitLabTaskRepository().update_gates("42", [_gate(GateStatus.RESOLVED)])

        assert _written_description(calls) == (
            "### Gates\n- **G-1** (human): Sign-off [resolved]\n### Acceptance Criteria\n- [ ] x"
        )

    def test_empty_gates_renders_placeholder(self) -> None:
        mock_run, calls = _view_and_update("### Gates\n- **G-1** (human): Sign-off [pending]")
        with patch("ydk.repositories.gitlab.tasks.run_glab", mock_run):
            GitLabTaskRepository().update_gates("42", [])

        assert _written_description(calls) == "### Gates\n_No gates_"

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_update_failure_raises(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed(stdout=json.dumps({"iid": 42, "description": ""})),
            _completed(returncode=1, stderr="denied"),
        ]

        with pytest.raises(RuntimeError, match="denied"):
            GitLabTaskRepository().update_gates("42", [_gate()])


# -- compact_task / compact_all_done (#703) ------------------------------------


class TestCompactTask:
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_posts_summary_note_and_archived_label(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed(stdout=json.dumps(_sample_issue_json(state="closed"))),
            _completed(),  # note
            _completed(),  # label
        ]

        compacted = GitLabTaskRepository().compact_task("42")

        note_cmd = mock_run.call_args_list[1].args[0]
        assert note_cmd[:5] == ["glab", "issue", "note", "42", "--message"]
        assert note_cmd[5].startswith("### Summary\n")
        assert compacted.summary in note_cmd[5]
        assert mock_run.call_args_list[2].args[0] == ["glab", "issue", "update", "42", "--label", "archived"]

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_open_task_is_not_compactable(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(stdout=json.dumps(_sample_issue_json(state="opened")))

        with pytest.raises(ValueError, match="not compactable"):
            GitLabTaskRepository().compact_task("42")
        assert mock_run.call_count == 1


class TestCompactAllDone:
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_dry_run_lists_closed_without_writing(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(stdout=json.dumps([_issue(1, state="closed"), _issue(2, state="closed")]))

        assert GitLabTaskRepository().compact_all_done(dry_run=True) == ["1", "2"]
        assert all(c.args[0][2] == "list" for c in mock_run.call_args_list)

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_skips_already_archived(self, mock_run: MagicMock) -> None:
        closed = [_issue(1, labels=["task", "archived"], state="closed"), _issue(2, state="closed")]
        mock_run.return_value = _completed(stdout=json.dumps(closed))

        assert GitLabTaskRepository().compact_all_done(dry_run=True) == ["2"]

    def test_compacts_each_closed_task_and_skips_failures(self) -> None:
        issues = {1: _issue(1, state="closed"), 2: _issue(2, state="closed")}
        writes: list[list[str]] = []

        def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
            if cmd[2] == "list":
                return _completed(stdout=json.dumps(list(issues.values())))
            if cmd[2] == "view":
                return _completed(stdout=json.dumps(issues[int(cmd[3])]))
            writes.append(cmd)
            if cmd[2] == "note" and cmd[3] == "1":
                return _completed(returncode=1, stderr="nope")
            return _completed()

        with patch("ydk.repositories.gitlab.tasks.run_glab", side_effect=run):
            assert GitLabTaskRepository().compact_all_done() == ["2"]
        assert ["glab", "issue", "update", "2", "--label", "archived"] in writes


# -- status derived from status:* labels -----------------------------------


class TestDerivedStatus:
    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("status:in-progress", TaskStatus.IN_PROGRESS),
            ("status:in-review", TaskStatus.IN_REVIEW),
            ("status:blocked", TaskStatus.BLOCKED_BY_CODE),
            ("status:blocked-by-code", TaskStatus.BLOCKED_BY_CODE),
            ("status:blocked-by-decision", TaskStatus.BLOCKED_BY_DECISION),
        ],
    )
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_get_reads_status_label(self, mock_run: MagicMock, label: str, expected: TaskStatus) -> None:
        mock_run.return_value = _completed(stdout=json.dumps(_issue(7, labels=["task", label])))

        assert GitLabTaskRepository().get(7).status == expected

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_closed_wins_over_status_label(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(
            stdout=json.dumps(_issue(7, labels=["task", "status:in-progress"], state="closed"))
        )

        assert GitLabTaskRepository().get(7).status == TaskStatus.DONE

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_bare_label_ignored(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(stdout=json.dumps(_issue(7, labels=["task", "in-progress"])))

        assert GitLabTaskRepository().get(7).status == TaskStatus.OPEN

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_list_ready_excludes_in_progress_and_blocked(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _fake_glab(
            [
                _issue(1),
                _issue(2, labels=["task", "status:in-progress"]),
                _issue(3, labels=["task", "status:blocked-by-code"]),
            ],
            [],
        )

        assert [t.id for t in GitLabTaskRepository().list_ready()] == ["1"]

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_list_tasks_reports_derived_status(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _fake_glab([_issue(2, labels=["task", "status:in-review"])], [])

        assert GitLabTaskRepository().list_tasks()[0].status == TaskStatus.IN_REVIEW


# -- check_dependencies / task_exists / assign / update_frontmatter (#717) ----


def _by_iid(issues: dict[int, dict]) -> Callable[[list[str]], subprocess.CompletedProcess[str]]:
    """Fake ``glab issue view N`` returning *issues[N]*; unknown IIDs fail like glab."""

    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        iid = int(cmd[3])
        if iid not in issues:
            return _completed(returncode=1, stderr="404 Not Found")
        return _completed(stdout=json.dumps(issues[iid]))

    return run


class TestCheckDependencies:
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_reports_resolved_and_unresolved_deps(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _by_iid({5: _issue(5, deps="#1, 2"), 1: _issue(1, state="closed"), 2: _issue(2)})

        deps = GitLabTaskRepository().check_dependencies("5")

        assert [(d.task_id, d.resolved) for d in deps] == [("#1", True), ("2", False)]

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_no_dependencies_returns_empty(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _by_iid({5: _issue(5)})

        assert GitLabTaskRepository().check_dependencies("#5") == []

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_missing_or_unparseable_dep_is_unresolved(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _by_iid({5: _issue(5, deps="99, not-an-id")})

        deps = GitLabTaskRepository().check_dependencies("5")

        assert [(d.task_id, d.resolved) for d in deps] == [("99", False), ("not-an-id", False)]

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_reads_deps_as_written_by_create(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(stdout="https://gitlab.com/owner/repo/-/issues/5\n")
        GitLabTaskRepository().create(TaskCreate(title="t", dependencies=["#1"]))
        cmd = mock_run.call_args[0][0]
        written = {**_issue(5), "description": cmd[cmd.index("--description") + 1]}
        mock_run.side_effect = _by_iid({5: written, 1: _issue(1, state="closed")})

        deps = GitLabTaskRepository().check_dependencies("5")

        assert [(d.task_id, d.resolved) for d in deps] == [("#1", True)]


class TestTaskExists:
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_existing_issue(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _by_iid({5: _issue(5)})

        assert GitLabTaskRepository().task_exists("#5") is True

    @pytest.mark.parametrize("task_id", ["404", "T-abc"])
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_missing_or_invalid_issue(self, mock_run: MagicMock, task_id: str) -> None:
        mock_run.side_effect = _by_iid({})

        assert GitLabTaskRepository().task_exists(task_id) is False


class TestAssign:
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_assigns_user(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed()

        GitLabTaskRepository().assign("#5", "alice")

        assert mock_run.call_args[0][0] == ["glab", "issue", "update", "5", "--assignee", "alice"]

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_unknown_assignee_is_ignored(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="user not found")

        GitLabTaskRepository().assign("5", "agent")  # must not raise


class TestUpdateFrontmatter:
    @staticmethod
    def _run(mock_run: MagicMock, fields: dict[str, object]) -> str:
        mock_run.return_value = _completed(stdout=json.dumps(_sample_issue_json()))
        GitLabTaskRepository().update_frontmatter("42", fields)
        update = mock_run.call_args[0][0]
        assert update[:4] == ["glab", "issue", "update", "42"]
        return update[update.index("--description") + 1]

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_writes_session_field(self, mock_run: MagicMock) -> None:
        body = self._run(mock_run, {"session_id": "abc"})

        assert "**Session**: abc" in body
        assert "### Acceptance Criteria" in body

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_dependencies_round_trip(self, mock_run: MagicMock) -> None:
        deps = ["#3", {"task_id": "#4", "type": "blocks"}, Dependency(task_id="7")]
        body = self._run(mock_run, {"dependencies": deps})

        mock_run.return_value = _completed(stdout=json.dumps({**_sample_issue_json(), "description": body}))
        assert GitLabTaskRepository().get(42).dependencies == ["#3", "#4", "7"]

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_replaces_existing_dependencies_and_clears_empty(self, mock_run: MagicMock) -> None:
        body = self._run(mock_run, {"dependencies": ["#9"]})
        assert "**Dependencies**: #9" in body
        assert "T-001" not in body

        body = self._run(mock_run, {"dependencies": []})
        assert "**Dependencies**" not in body

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_unknown_key_raises(self, mock_run: MagicMock) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            GitLabTaskRepository().update_frontmatter("42", {"bogus": 1})
        mock_run.assert_not_called()


class TestStartClearsBlockedLabels:
    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_in_progress_unlabels_known_blocked_set_without_reading(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed()

        GitLabTaskRepository().update_status("5", "in-progress")

        mock_run.assert_called_once_with(
            [
                "glab",
                "issue",
                "update",
                "5",
                "--label",
                "status:in-progress",
                "--unlabel",
                "status:blocked,status:blocked-by-code,status:blocked-by-decision",
            ]
        )

    @patch("ydk.repositories.gitlab.tasks.run_glab")
    def test_started_blocked_task_reads_in_progress(self, mock_run: MagicMock) -> None:
        labels = ["task", "status:blocked-by-code"]

        def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
            if "--unlabel" in cmd:
                for lbl in cmd[cmd.index("--unlabel") + 1].split(","):
                    if lbl in labels:
                        labels.remove(lbl)
            if "--label" in cmd:
                labels.append(cmd[cmd.index("--label") + 1])
            return _completed(stdout=json.dumps(_issue(5, labels=list(labels))))

        mock_run.side_effect = run
        repo = GitLabTaskRepository()

        repo.update_status("5", "in-progress")

        assert repo.get(5).status == TaskStatus.IN_PROGRESS

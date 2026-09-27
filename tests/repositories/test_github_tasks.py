"""Tests for GitHubTaskRepository — all subprocess calls mocked."""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from ydk.models.gate import Gate, GateStatus, GateType
from ydk.models.pm import AcceptanceCriterion, Dependency, DependencyType, TaskCreate, TaskStatus
from ydk.repositories.github.tasks import GitHubTaskRepository, _extract_issue_number


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

    def test_raises_on_failure(self) -> None:
        repo = GitHubTaskRepository()
        fake = _fake_run(returncode=1, stderr="network error")
        with (
            patch("ydk.repositories.github.tasks.run_gh", return_value=fake),
            pytest.raises(RuntimeError, match="network error"),
        ):
            repo.list()

    def test_status_open_maps_to_state_open(self) -> None:
        repo = GitHubTaskRepository()
        fake = _fake_run(stdout="[]")
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake) as mock_run:
            repo.list(status="open")
        cmd = mock_run.call_args[0][0]
        assert cmd[cmd.index("--state") + 1] == "open"

    def test_status_done_maps_to_state_closed(self) -> None:
        repo = GitHubTaskRepository()
        fake = _fake_run(stdout="[]")
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake) as mock_run:
            repo.list(status="done")
        cmd = mock_run.call_args[0][0]
        assert cmd[cmd.index("--state") + 1] == "closed"

    def test_status_in_progress_maps_to_open_plus_label(self) -> None:
        repo = GitHubTaskRepository()
        fake = _fake_run(stdout="[]")
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake) as mock_run:
            repo.list(status="in-progress")
        cmd = mock_run.call_args[0][0]
        assert cmd[cmd.index("--state") + 1] == "open"
        assert "in-progress" in cmd
        # Base task label filter must still be present alongside the status label.
        label_values = [cmd[i + 1] for i, v in enumerate(cmd) if v == "--label"]
        assert "task" in label_values
        assert "in-progress" in label_values

    def test_status_in_review_maps_to_open_plus_label(self) -> None:
        repo = GitHubTaskRepository()
        fake = _fake_run(stdout="[]")
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake) as mock_run:
            repo.list(status="in-review")
        cmd = mock_run.call_args[0][0]
        assert cmd[cmd.index("--state") + 1] == "open"
        assert "in-review" in cmd
        label_values = [cmd[i + 1] for i, v in enumerate(cmd) if v == "--label"]
        assert "task" in label_values
        assert "in-review" in label_values

    def test_status_closed_maps_to_state_closed(self) -> None:
        repo = GitHubTaskRepository()
        fake = _fake_run(stdout="[]")
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake) as mock_run:
            repo.list(status="closed")
        cmd = mock_run.call_args[0][0]
        assert cmd[cmd.index("--state") + 1] == "closed"

    def test_status_blocked_fetches_open_and_filters_by_parsed_status(self) -> None:
        repo = GitHubTaskRepository()
        items = [
            {
                "number": 1,
                "title": "Blocked one",
                "state": "OPEN",
                "labels": [{"name": "task"}, {"name": "blocked-by-code"}],
                "body": "",
                "url": "https://github.com/org/repo/issues/1",
            },
            {
                "number": 2,
                "title": "Not blocked",
                "state": "OPEN",
                "labels": [{"name": "task"}],
                "body": "",
                "url": "https://github.com/org/repo/issues/2",
            },
        ]
        fake = _fake_run(stdout=json.dumps(items))
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake) as mock_run:
            result = repo.list(status="blocked")

        cmd = mock_run.call_args[0][0]
        assert cmd[cmd.index("--state") + 1] == "open"
        assert len(result) == 1
        assert result[0].number == 1

    def test_status_all_maps_to_state_all(self) -> None:
        repo = GitHubTaskRepository()
        fake = _fake_run(stdout="[]")
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake) as mock_run:
            repo.list(status="all")
        cmd = mock_run.call_args[0][0]
        assert cmd[cmd.index("--state") + 1] == "all"


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


# ---------------------------------------------------------------------------
# compact_task
# ---------------------------------------------------------------------------


class TestCompactTask:
    def _issue_json(self) -> str:
        return json.dumps(
            {
                "number": 42,
                "title": "Validate orders",
                "state": "CLOSED",
                "labels": [{"name": "task"}],
                "body": (
                    "**Story**: S-001\n\n### Description\nValidation logic\n\n### Acceptance Criteria\n- [x] It works"
                ),
                "url": "https://github.com/org/repo/issues/42",
            }
        )

    def test_does_not_overwrite_issue_body(self) -> None:
        """compact_task must never call `gh issue edit --body` on the issue."""
        repo = GitHubTaskRepository()
        fake_get = _fake_run(stdout=self._issue_json())
        fake_ok = _fake_run()

        def _dispatch(cmd: list[object], **_kwargs: object) -> MagicMock:
            if "view" in cmd:
                return fake_get
            return fake_ok

        with patch("ydk.repositories.github.tasks.run_gh", side_effect=_dispatch) as mock_run:
            repo.compact_task("42")

        for call in mock_run.call_args_list:
            cmd = call[0][0]
            assert not (cmd[:2] == ["gh", "issue"] and "edit" in cmd and "--body" in cmd), (
                f"compact_task must not overwrite the issue body via: {cmd}"
            )

    def test_posts_summary_as_comment_and_archives(self) -> None:
        repo = GitHubTaskRepository()
        fake_get = _fake_run(stdout=self._issue_json())
        fake_ok = _fake_run()

        def _dispatch(cmd: list[object], **_kwargs: object) -> MagicMock:
            if "view" in cmd:
                return fake_get
            return fake_ok

        with patch("ydk.repositories.github.tasks.run_gh", side_effect=_dispatch) as mock_run:
            compacted = repo.compact_task("42")

        assert compacted.title == "Validate orders"
        assert "Completed" in compacted.summary

        comment_calls = [c[0][0] for c in mock_run.call_args_list if "comment" in c[0][0]]
        assert len(comment_calls) == 1
        assert "--body" in comment_calls[0]
        assert any("Completed" in str(a) for a in comment_calls[0])

        label_calls = [c[0][0] for c in mock_run.call_args_list if "--add-label" in c[0][0]]
        assert len(label_calls) == 1
        assert "archived" in [str(a) for a in label_calls[0]]


# ---------------------------------------------------------------------------
# Round-trip persistence of gates / tdd_stage / session_id
# ---------------------------------------------------------------------------


class _FakeGhIssue:
    """In-memory stand-in for the gh CLI boundary holding one issue body."""

    def __init__(self, body: str) -> None:
        self.body = body

    def __call__(self, cmd: list[str], *args: object, **kwargs: object) -> MagicMock:
        if cmd[:3] == ["gh", "issue", "view"]:
            if "-q" in cmd:
                return _fake_run(stdout=self.body + "\n")
            payload = {"number": 42, "title": "T", "state": "OPEN", "labels": [], "body": self.body, "url": ""}
            return _fake_run(stdout=json.dumps(payload))
        if cmd[:3] == ["gh", "issue", "edit"] and "--body" in cmd:
            self.body = cmd[cmd.index("--body") + 1]
        return _fake_run()


_BASE_BODY = "**Story**: #1\n**Dependencies**: #5\n\n### Description\nDo it\n\n### Acceptance Criteria\n- [ ] Works"


class TestFieldPersistenceRoundTrip:
    def test_update_gates_then_get_task_returns_same_gates(self) -> None:
        fake = _FakeGhIssue(_BASE_BODY)
        repo = GitHubTaskRepository()
        gates = [
            Gate(id="G-1", type=GateType.HUMAN, description="Approval", status=GateStatus.RESOLVED),
            Gate(id="G-2", type=GateType.PR_MERGED, description="Upstream", config={"pr": "7"}),
        ]
        with patch("ydk.repositories.github.tasks.run_gh", side_effect=fake):
            repo.update_gates("42", gates)
            detail = repo.get_task("42")
        assert detail.gates == gates
        assert detail.description == "Do it"
        assert [ac.text for ac in detail.acceptance_criteria if isinstance(ac, AcceptanceCriterion)] == ["Works"]

    def test_adding_gate_appends_rather_than_overwrites(self) -> None:
        fake = _FakeGhIssue(_BASE_BODY)
        repo = GitHubTaskRepository()
        first = Gate(id="G-1", type=GateType.HUMAN, description="Approval")
        second = Gate(id="G-2", type=GateType.TIMER, description="Wait")
        with patch("ydk.repositories.github.tasks.run_gh", side_effect=fake):
            repo.update_gates("42", [first])
            existing = repo.get_task("42").gates
            repo.update_gates("42", [*existing, second])
            detail = repo.get_task("42")
        assert [g.id for g in detail.gates] == ["G-1", "G-2"]

    def test_tdd_stage_round_trip(self) -> None:
        fake = _FakeGhIssue(_BASE_BODY)
        repo = GitHubTaskRepository()
        with patch("ydk.repositories.github.tasks.run_gh", side_effect=fake):
            repo.update_frontmatter("42", {"tdd_stage": "red"})
            assert repo.get_task("42").tdd_stage == "red"
            repo.update_frontmatter("42", {"tdd_stage": "green"})
            detail = repo.get_task("42")
        assert detail.tdd_stage == "green"
        assert fake.body.count("**TDD stage**") == 1
        assert detail.story_id == "#1"
        assert detail.description == "Do it"

    def test_session_id_round_trip(self) -> None:
        fake = _FakeGhIssue(_BASE_BODY)
        repo = GitHubTaskRepository()
        with patch("ydk.repositories.github.tasks.run_gh", side_effect=fake):
            repo.update_frontmatter("42", {"session_id": "sess-1"})
            detail = repo.get_task("42")
        assert detail.session_id == "sess-1"

    def test_field_added_to_body_without_header_fields(self) -> None:
        fake = _FakeGhIssue("### Description\nOnly a description")
        repo = GitHubTaskRepository()
        with patch("ydk.repositories.github.tasks.run_gh", side_effect=fake):
            repo.update_frontmatter("42", {"tdd_stage": "refactor"})
            detail = repo.get_task("42")
        assert detail.tdd_stage == "refactor"
        assert detail.description == "Only a description"

    def test_dependencies_still_replaced(self) -> None:
        fake = _FakeGhIssue(_BASE_BODY)
        repo = GitHubTaskRepository()
        with patch("ydk.repositories.github.tasks.run_gh", side_effect=fake):
            repo.update_frontmatter("42", {"dependencies": ["#8", "#9"]})
            detail = repo.get_task("42")
        assert detail.dependencies == [Dependency(task_id="#8"), Dependency(task_id="#9")]

    def test_dependency_types_persist(self) -> None:
        fake = _FakeGhIssue(_BASE_BODY)
        repo = GitHubTaskRepository()
        deps = [
            Dependency(task_id="#8"),
            {"task_id": "#9", "type": "related"},
            Dependency(task_id="#10", type=DependencyType.VALIDATES),
        ]
        with patch("ydk.repositories.github.tasks.run_gh", side_effect=fake):
            repo.update_frontmatter("42", {"dependencies": deps})
            detail = repo.get_task("42")
        assert "**Dependencies**: #8, #9 (related), #10 (validates)" in fake.body
        assert detail.dependencies == [
            Dependency(task_id="#8"),
            Dependency(task_id="#9", type=DependencyType.RELATED),
            Dependency(task_id="#10", type=DependencyType.VALIDATES),
        ]

    def test_unknown_key_raises_without_calling_gh(self) -> None:
        repo = GitHubTaskRepository()
        with (
            patch("ydk.repositories.github.tasks.run_gh") as mock_run,
            pytest.raises(ValueError, match="bogus"),
        ):
            repo.update_frontmatter("42", {"bogus": "x"})
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# _extract_issue_number (strict parser)
# ---------------------------------------------------------------------------


class TestExtractIssueNumber:
    @pytest.mark.parametrize(("raw", "expected"), [("12", 12), ("#12", 12), (" #7 ", 7)])
    def test_accepts_digits_or_hash_digits(self, raw: str, expected: int) -> None:
        assert _extract_issue_number(raw) == expected

    @pytest.mark.parametrize("raw", ["T-5e9dbd18", "QD-abc123", "T-12345678", "T-001", "", "#", "abc", "1.5"])
    def test_rejects_non_issue_ids_with_clear_error(self, raw: str) -> None:
        with pytest.raises(ValueError, match=r"is not a GitHub issue number; remote=github expects N or #N") as exc:
            _extract_issue_number(raw)
        assert repr(raw) in str(exc.value)


# ---------------------------------------------------------------------------
# list_ready / list_tasks — dependency-type-aware readiness
# ---------------------------------------------------------------------------


def _issue(number: int, deps: str = "", state: str = "OPEN") -> dict[str, object]:
    body = f"**Dependencies**: {deps}\n\n### Description\nx" if deps else "### Description\nx"
    return {
        "number": number,
        "title": f"T{number}",
        "state": state,
        "labels": [{"name": "task"}],
        "body": body,
        "url": "",
    }


class _FakeGhList:
    """gh CLI boundary stand-in serving ``issue list`` for open/closed/all states."""

    def __init__(self, open_issues: list[dict[str, object]], closed_issues: list[dict[str, object]]) -> None:
        self.open_issues = open_issues
        self.closed_issues = [{**i, "state": "CLOSED"} for i in closed_issues]

    def __call__(self, cmd: list[str], *args: object, **kwargs: object) -> MagicMock:
        state = cmd[cmd.index("--state") + 1]
        issues = {"open": self.open_issues, "closed": self.closed_issues}.get(
            state, self.open_issues + self.closed_issues
        )
        return _fake_run(stdout=json.dumps(issues))


def _ready_ids(fake: _FakeGhList) -> list[str]:
    with patch("ydk.repositories.github.tasks.run_gh", side_effect=fake):
        return [t.id for t in GitHubTaskRepository().list_ready()]


def _deps_met(fake: _FakeGhList, state: str = "open") -> dict[str, bool]:
    with patch("ydk.repositories.github.tasks.run_gh", side_effect=fake):
        return {t.id: t.dependencies_met for t in GitHubTaskRepository().list_tasks(state=state)}


class TestListReadyDependencyTypes:
    @pytest.mark.parametrize("dep_type", ["related", "validates"])
    def test_non_blocking_open_dependency_does_not_block(self, dep_type: str) -> None:
        fake = _FakeGhList([_issue(1), _issue(2, f"#1 ({dep_type})")], [])
        assert "2" in _ready_ids(fake)

    def test_open_blocks_dependency_blocks(self) -> None:
        fake = _FakeGhList([_issue(1), _issue(2, "#1")], [])
        assert _ready_ids(fake) == ["1"]

    def test_closed_blocks_dependency_does_not_block(self) -> None:
        fake = _FakeGhList([_issue(2, "#1 (waits-for)")], [_issue(1)])
        assert _ready_ids(fake) == ["2"]

    def test_non_blocking_dependency_not_counted_as_dependent(self) -> None:
        fake = _FakeGhList([_issue(1), _issue(2), _issue(3, "#2 (related)")], [])
        with patch("ydk.repositories.github.tasks.run_gh", side_effect=fake):
            counts = {t.id: t.dependents_count for t in GitHubTaskRepository().list_ready()}
        assert counts["2"] == 0

    def test_unresolvable_dependency_warns_and_is_unmet(self, caplog: pytest.LogCaptureFixture) -> None:
        fake = _FakeGhList([_issue(2, "T-5e9dbd18")], [])
        with caplog.at_level(logging.WARNING, logger="ydk.repositories.github.tasks"):
            assert _ready_ids(fake) == []
        assert any("#2" in r.getMessage() and "T-5e9dbd18" in r.getMessage() for r in caplog.records)


class TestListTasksDependencyTypes:
    def test_non_blocking_open_dependency_is_met(self) -> None:
        fake = _FakeGhList([_issue(1), _issue(2, "#1 (related)")], [])
        assert _deps_met(fake)["2"] is True

    def test_open_blocks_dependency_is_unmet(self) -> None:
        fake = _FakeGhList([_issue(1), _issue(2, "#1")], [])
        assert _deps_met(fake)["2"] is False

    def test_closed_blocks_dependency_is_met(self) -> None:
        fake = _FakeGhList([_issue(2, "#1")], [_issue(1)])
        assert _deps_met(fake, state="all")["2"] is True

    def test_unresolvable_dependency_warns_and_is_unmet(self, caplog: pytest.LogCaptureFixture) -> None:
        fake = _FakeGhList([_issue(2, "QD-abc123")], [])
        with caplog.at_level(logging.WARNING, logger="ydk.repositories.github.tasks"):
            assert _deps_met(fake)["2"] is False
        assert any("#2" in r.getMessage() and "QD-abc123" in r.getMessage() for r in caplog.records)

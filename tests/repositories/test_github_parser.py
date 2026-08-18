"""Tests for the GitHub Issue body parser — round-trip and edge cases."""

from ydk.models.pm import AcceptanceCriterion, EpicCreate, StoryCreate, TaskCreate, TaskStatus
from ydk.repositories.github.parser import (
    _github_ref,
    parse_epic_detail,
    parse_story_detail,
    parse_task_detail,
    render_epic_body,
    render_story_body,
    render_task_body,
)

# ---------------------------------------------------------------------------
# Task round-trip
# ---------------------------------------------------------------------------


class TestTaskRoundTrip:
    """TaskCreate -> render -> parse -> fields match."""

    def test_full_round_trip(self) -> None:
        task = TaskCreate(
            title="Validate orders",
            story_id="6",
            spec_refs=["orders.md#entities", "orders.md#error-scenarios"],
            dependencies=["T-001", "T-003"],
            test_strategy="Unit tests for domain validation",
            description="Implement order validation rules with proper error codes.",
            acceptance_criteria=[
                AcceptanceCriterion(text="Insufficient balance raises INSUFFICIENT_BALANCE"),
                AcceptanceCriterion(text="Invalid symbol raises INVALID_SYMBOL"),
            ],
        )
        body = render_task_body(task)
        # GitHub renderer converts story_id "6" -> "#6"
        assert "**Story**: #6" in body
        detail = parse_task_detail(
            number=42,
            title=task.title,
            body=body,
            state="OPEN",
            labels=["task"],
        )

        assert detail.number == 42
        assert detail.title == task.title
        assert detail.story_id == "#6"
        assert detail.spec_refs == task.spec_refs
        assert detail.dependencies == task.dependencies
        assert detail.test_strategy == task.test_strategy
        assert detail.description == task.description
        assert len(detail.acceptance_criteria) == len(task.acceptance_criteria)
        for parsed, original in zip(detail.acceptance_criteria, task.acceptance_criteria, strict=True):
            assert parsed.text == original.text
            assert parsed.done == original.done
        assert detail.status == TaskStatus.OPEN

    def test_minimal_round_trip(self) -> None:
        task = TaskCreate(title="Bare minimum task")
        body = render_task_body(task)
        detail = parse_task_detail(
            number=1,
            title=task.title,
            body=body,
            state="OPEN",
            labels=[],
        )
        assert detail.title == "Bare minimum task"
        assert detail.story_id is None
        assert detail.spec_refs == []
        assert detail.dependencies == []
        assert detail.acceptance_criteria == []

    def test_done_criteria_preserved(self) -> None:
        task = TaskCreate(
            title="With done criteria",
            acceptance_criteria=[
                AcceptanceCriterion(text="Already done", done=True),
                AcceptanceCriterion(text="Not done yet", done=False),
            ],
        )
        body = render_task_body(task)
        detail = parse_task_detail(number=5, title=task.title, body=body, state="OPEN", labels=[])
        assert detail.acceptance_criteria[0].done is True
        assert detail.acceptance_criteria[1].done is False


# ---------------------------------------------------------------------------
# Task status mapping
# ---------------------------------------------------------------------------


class TestTaskStatusMapping:
    def test_closed_maps_to_done(self) -> None:
        detail = parse_task_detail(number=1, title="T", body="", state="CLOSED", labels=[])
        assert detail.status == TaskStatus.DONE

    def test_blocked_label(self) -> None:
        detail = parse_task_detail(number=1, title="T", body="", state="OPEN", labels=["blocked"])
        assert detail.status == TaskStatus.BLOCKED_BY_CODE

    def test_in_progress_label(self) -> None:
        detail = parse_task_detail(number=1, title="T", body="", state="OPEN", labels=["in-progress"])
        assert detail.status == TaskStatus.IN_PROGRESS

    def test_in_progress_underscore_label(self) -> None:
        detail = parse_task_detail(number=1, title="T", body="", state="OPEN", labels=["in_progress"])
        assert detail.status == TaskStatus.IN_PROGRESS

    def test_open_is_default(self) -> None:
        detail = parse_task_detail(number=1, title="T", body="", state="OPEN", labels=["task", "p1"])
        assert detail.status == TaskStatus.OPEN


# ---------------------------------------------------------------------------
# Parser edge cases
# ---------------------------------------------------------------------------


class TestParserEdgeCases:
    def test_empty_body(self) -> None:
        detail = parse_task_detail(number=1, title="T", body="", state="OPEN", labels=[])
        assert detail.description == ""
        assert detail.acceptance_criteria == []
        assert detail.story_id is None

    def test_none_body(self) -> None:
        detail = parse_task_detail(number=1, title="T", body=None, state="OPEN", labels=[])
        assert detail.description == ""

    def test_body_with_extra_whitespace(self) -> None:
        body = "**Story**: #6\n\n\n### Description\n  \n  Some text  \n\n### Acceptance Criteria\n- [ ] Item one\n"
        detail = parse_task_detail(number=1, title="T", body=body, state="OPEN", labels=[])
        assert detail.story_id == "#6"
        assert "Some text" in detail.description
        assert len(detail.acceptance_criteria) == 1

    def test_missing_optional_fields(self) -> None:
        body = "### Description\nJust a description, no metadata fields."
        detail = parse_task_detail(number=1, title="T", body=body, state="OPEN", labels=[])
        assert detail.story_id is None
        assert detail.spec_refs == []
        assert detail.dependencies == []
        assert detail.test_strategy == ""
        assert "Just a description" in detail.description


# ---------------------------------------------------------------------------
# Story round-trip
# ---------------------------------------------------------------------------


class TestStoryRoundTrip:
    def test_full_round_trip(self) -> None:
        story = StoryCreate(
            title="User places an order",
            epic_id="5",
            description="As a trader I want to place orders.",
            acceptance_criteria=[
                AcceptanceCriterion(text="Can submit a buy order"),
                AcceptanceCriterion(text="Gets confirmation", done=True),
            ],
        )
        body = render_story_body(story)
        # GitHub renderer converts epic_id "5" -> "#5"
        assert "**Epic**: #5" in body
        detail = parse_story_detail(number=10, title=story.title, body=body, state="OPEN", labels=["story"])

        assert detail.number == 10
        assert detail.title == story.title
        assert detail.epic_id == "#5"
        assert "As a trader" in detail.description
        assert len(detail.acceptance_criteria) == 2
        assert detail.acceptance_criteria[1].done is True
        assert detail.status == TaskStatus.OPEN

    def test_minimal_round_trip(self) -> None:
        story = StoryCreate(title="Bare story")
        body = render_story_body(story)
        detail = parse_story_detail(number=2, title=story.title, body=body, state="OPEN", labels=[])
        assert detail.epic_id is None
        assert detail.acceptance_criteria == []


# ---------------------------------------------------------------------------
# Epic round-trip
# ---------------------------------------------------------------------------


class TestEpicRoundTrip:
    def test_full_round_trip(self) -> None:
        epic = EpicCreate(title="Orders", description="Everything about orders.")
        body = render_epic_body(epic)
        detail = parse_epic_detail(number=1, title=epic.title, body=body, state="OPEN", labels=["epic"])

        assert detail.number == 1
        assert detail.title == "Orders"
        assert "Everything about orders" in detail.description
        assert detail.status == TaskStatus.OPEN

    def test_empty_description(self) -> None:
        epic = EpicCreate(title="Empty epic")
        body = render_epic_body(epic)
        detail = parse_epic_detail(number=2, title=epic.title, body=body, state="CLOSED", labels=[])
        assert detail.description == ""
        assert detail.status == TaskStatus.DONE


# ---------------------------------------------------------------------------
# GitHub reference formatting
# ---------------------------------------------------------------------------


class TestGithubRef:
    def test_bare_number(self) -> None:
        assert _github_ref("42") == "#42"

    def test_s_prefix(self) -> None:
        assert _github_ref("S-001") == "#1"

    def test_e_prefix(self) -> None:
        assert _github_ref("E-005") == "#5"

    def test_t_prefix(self) -> None:
        assert _github_ref("T-010") == "#10"

    def test_already_prefixed(self) -> None:
        assert _github_ref("#7") == "#7"

    def test_render_task_body_uses_hash_ref(self) -> None:
        task = TaskCreate(title="Test", story_id="S-003")
        body = render_task_body(task)
        assert "**Story**: #3" in body

    def test_render_story_body_uses_hash_ref(self) -> None:
        story = StoryCreate(title="Test", epic_id="E-002")
        body = render_story_body(story)
        assert "**Epic**: #2" in body

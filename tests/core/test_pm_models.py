"""Tests for project-management Pydantic models."""

import pytest
from pydantic import ValidationError

from odk.models.pm import (
    AcceptanceCriterion,
    EpicCreate,
    EpicDetail,
    StoryCreate,
    StoryDetail,
    TaskCreate,
    TaskDetail,
    TaskStatus,
)

# ---------------------------------------------------------------------------
# AcceptanceCriterion
# ---------------------------------------------------------------------------


class TestAcceptanceCriterion:
    def test_defaults_done_false(self) -> None:
        ac = AcceptanceCriterion(text="stuff works")
        assert ac.done is False

    def test_done_true(self) -> None:
        ac = AcceptanceCriterion(text="stuff works", done=True)
        assert ac.done is True

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            AcceptanceCriterion(text="ok", extra="bad")


# ---------------------------------------------------------------------------
# TaskStatus
# ---------------------------------------------------------------------------


class TestTaskStatus:
    def test_values(self) -> None:
        assert TaskStatus.OPEN == "open"
        assert TaskStatus.IN_PROGRESS == "in-progress"
        assert TaskStatus.BLOCKED_BY_CODE == "blocked-by-code"
        assert TaskStatus.BLOCKED_BY_DECISION == "blocked-by-decision"
        assert TaskStatus.IN_REVIEW == "in-review"
        assert TaskStatus.DONE == "done"
        assert TaskStatus.CLOSED == "closed"

    def test_lifecycle_status_values_match_hyphen_convention(self) -> None:
        """Enum values use hyphens to match what task_lifecycle.py writes."""
        assert "-" in TaskStatus.IN_PROGRESS.value
        assert "-" in TaskStatus.BLOCKED_BY_CODE.value
        assert "-" in TaskStatus.BLOCKED_BY_DECISION.value
        assert "-" in TaskStatus.IN_REVIEW.value


# ---------------------------------------------------------------------------
# TaskCreate
# ---------------------------------------------------------------------------


class TestTaskCreate:
    def test_minimal(self) -> None:
        t = TaskCreate(title="Do the thing")
        assert t.title == "Do the thing"
        assert t.story_id is None
        assert t.spec_refs == []
        assert t.dependencies == []
        assert t.test_strategy == ""
        assert t.description == ""
        assert t.acceptance_criteria == []
        assert t.labels == []
        assert t.milestone is None

    def test_full(self) -> None:
        t = TaskCreate(
            title="Validate orders",
            story_id="S-001",
            spec_refs=["orders.md#entities"],
            dependencies=["T-001"],
            test_strategy="Unit tests",
            description="Implement validation",
            acceptance_criteria=[AcceptanceCriterion(text="It works")],
            labels=["p1"],
            milestone="v1.0",
        )
        assert t.story_id == "S-001"
        assert len(t.acceptance_criteria) == 1
        assert t.acceptance_criteria[0].text == "It works"

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            TaskCreate(title="x", bogus=True)


# ---------------------------------------------------------------------------
# TaskDetail
# ---------------------------------------------------------------------------


class TestTaskDetail:
    def test_defaults(self) -> None:
        td = TaskDetail(number=42, title="T")
        assert td.status == TaskStatus.OPEN
        assert td.url == ""
        assert td.labels == []

    def test_full(self) -> None:
        td = TaskDetail(
            number=7,
            title="Full",
            story_id="S-001",
            spec_refs=["a.md"],
            dependencies=["T-001"],
            test_strategy="integration",
            description="desc",
            acceptance_criteria=[AcceptanceCriterion(text="c1", done=True)],
            labels=["task", "p1"],
            status=TaskStatus.DONE,
            url="https://github.com/org/repo/issues/7",
        )
        assert td.number == 7
        assert td.status == TaskStatus.DONE
        assert td.acceptance_criteria[0].done is True


# ---------------------------------------------------------------------------
# StoryCreate / StoryDetail
# ---------------------------------------------------------------------------


class TestStoryCreate:
    def test_minimal(self) -> None:
        s = StoryCreate(title="User can place order")
        assert s.epic_id is None
        assert s.acceptance_criteria == []

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            StoryCreate(title="x", bogus=True)


class TestStoryDetail:
    def test_defaults(self) -> None:
        sd = StoryDetail(number=3, title="S")
        assert sd.status == TaskStatus.OPEN
        assert sd.epic_id is None


# ---------------------------------------------------------------------------
# EpicCreate / EpicDetail
# ---------------------------------------------------------------------------


class TestEpicCreate:
    def test_minimal(self) -> None:
        e = EpicCreate(title="Orders epic")
        assert e.description == ""
        assert e.labels == []

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            EpicCreate(title="x", bogus=True)


class TestEpicDetail:
    def test_defaults(self) -> None:
        ed = EpicDetail(number=1, title="E")
        assert ed.status == TaskStatus.OPEN
        assert ed.url == ""

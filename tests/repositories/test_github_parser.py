"""Tests for the GitHub Issue body parser — round-trip and edge cases."""

from ydk.models.gate import Gate, GateStatus, GateType
from ydk.models.pm import AcceptanceCriterion, EpicCreate, StoryCreate, TaskCreate, TaskStatus
from ydk.repositories.github.parser import (
    _github_ref,
    parse_epic_detail,
    parse_story_detail,
    parse_task_detail,
    render_epic_body,
    render_gate_line,
    render_story_body,
    render_task_body,
    set_body_field,
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


# ---------------------------------------------------------------------------
# Gates / TDD stage / session parsing
# ---------------------------------------------------------------------------


class TestTaskLifecycleFieldParsing:
    """parse_task_detail reads back gates, tdd_stage and session_id from the body."""

    def test_parses_gates_section(self) -> None:
        gates = [
            Gate(id="G-1", type=GateType.HUMAN, description="Approval: from lead", status=GateStatus.RESOLVED),
            Gate(id="G-2", type=GateType.PR_MERGED, description="Wait [upstream]", config={"pr": "12"}),
        ]
        body = "**Story**: #1\n\n### Description\nDo it\n\n### Gates\n" + "\n".join(render_gate_line(g) for g in gates)
        detail = parse_task_detail(1, "T", body, "OPEN", [])
        assert detail.gates == gates
        assert detail.description == "Do it"

    def test_parses_legacy_gate_line_without_metadata(self) -> None:
        body = "### Gates\n- **G-9** (timer): Wait a day [pending]"
        detail = parse_task_detail(1, "T", body, "OPEN", [])
        assert len(detail.gates) == 1
        assert detail.gates[0].id == "G-9"
        assert detail.gates[0].type == GateType.TIMER
        assert detail.gates[0].description == "Wait a day"
        assert detail.gates[0].status == GateStatus.PENDING

    def test_no_gates_placeholder_yields_empty(self) -> None:
        detail = parse_task_detail(1, "T", "### Gates\n_No gates_", "OPEN", [])
        assert detail.gates == []

    def test_parses_tdd_stage_and_session(self) -> None:
        body = "**Story**: #1\n**TDD stage**: green\n**Session**: sess-abc\n\n### Description\nx"
        detail = parse_task_detail(1, "T", body, "OPEN", [])
        assert detail.tdd_stage == "green"
        assert detail.session_id == "sess-abc"

    def test_missing_fields_default_none(self) -> None:
        detail = parse_task_detail(1, "T", "### Description\nx", "OPEN", [])
        assert detail.tdd_stage is None
        assert detail.session_id is None
        assert detail.gates == []

    def test_render_task_body_includes_gates_round_trip(self) -> None:
        gates = [Gate(id="G-1", type=GateType.CUSTOM, description="Other", resolved_at="2026-01-01T00:00:00Z")]
        task = TaskCreate(title="T", description="d", acceptance_criteria=["a"], gates=gates)
        detail = parse_task_detail(1, "T", render_task_body(task), "OPEN", [])
        assert detail.gates == gates
        assert detail.description == "d"

    def test_gate_metadata_cannot_close_html_comment(self) -> None:
        gate = Gate(id="G-1", type=GateType.CUSTOM, description="x", config={"k": "a --> b"})
        assert "-->" not in render_gate_line(gate).removesuffix(" -->")
        detail = parse_task_detail(1, "T", "### Gates\n" + render_gate_line(gate), "OPEN", [])
        assert detail.gates == [gate]


class TestSetBodyField:
    def test_replaces_existing_field(self) -> None:
        body = "**Story**: #1\n**TDD stage**: red\n\n### Description\nx"
        assert set_body_field(body, "TDD stage", "green") == "**Story**: #1\n**TDD stage**: green\n\n### Description\nx"

    def test_adds_after_last_header_field(self) -> None:
        body = "**Story**: #1\n\n### Description\n**Session**: not-a-field"
        out = set_body_field(body, "Session", "s1")
        assert out == "**Story**: #1\n**Session**: s1\n\n### Description\n**Session**: not-a-field"

    def test_adds_to_empty_body(self) -> None:
        assert set_body_field("", "Session", "s1") == "**Session**: s1"

    def test_empty_value_removes_field(self) -> None:
        body = "**Story**: #1\n**Dependencies**: #2\n\n### Description\nx"
        assert set_body_field(body, "Dependencies", "") == "**Story**: #1\n\n### Description\nx"

    def test_invalid_gate_lines_are_skipped_with_warning(self, caplog) -> None:
        body = (
            "### Gates\n"
            "- **G-1** (bogus-type): x [pending]\n"
            "- **G-2** (human): x [weird]\n"
            "- **G-3** (human): x [pending] <!-- ydk-gate {not json} -->\n"
            "- **G-4** (human): ok [pending]"
        )
        with caplog.at_level("WARNING"):
            detail = parse_task_detail(1, "T", body, "OPEN", [])
        assert [g.id for g in detail.gates] == ["G-4"]
        assert caplog.text.count("Skipping unparseable gate line") == 3

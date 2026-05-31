"""Tests for the GitLab (backend-agnostic) structured body parser.

Round-trip: render -> parse should recover the original fields.
Edge cases: empty fields, missing sections, partial metadata.
"""

from __future__ import annotations

import pytest

from odk.models.pm import AcceptanceCriterion
from odk.repositories.gitlab.parser import parse_body, render_body

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def full_body_fields() -> dict:
    return {
        "story_id": "S-001",
        "spec_refs": ["orders.md#entities", "orders.md#error-scenarios"],
        "dependencies": ["T-001", "T-003"],
        "test_strategy": "Unit tests for domain validation",
        "description": "Implement the order aggregate root with validation.",
        "acceptance_criteria": [
            AcceptanceCriterion(text="Order entity validates required fields", done=False),
            AcceptanceCriterion(text="Invalid orders raise DomainError", done=True),
        ],
    }


@pytest.fixture
def full_body_text() -> str:
    return (
        "**Story**: S-001\n"
        "**Spec refs**: orders.md#entities, orders.md#error-scenarios\n"
        "**Dependencies**: T-001, T-003\n"
        "**Test strategy**: Unit tests for domain validation\n"
        "\n"
        "### Description\n"
        "Implement the order aggregate root with validation.\n"
        "\n"
        "### Acceptance Criteria\n"
        "- [ ] Order entity validates required fields\n"
        "- [x] Invalid orders raise DomainError"
    )


# ── render_body ───────────────────────────────────────────────────────


class TestRenderBody:
    def test_full_render(self, full_body_fields: dict, full_body_text: str) -> None:
        result = render_body(**full_body_fields)
        assert result == full_body_text

    def test_empty_optional_fields(self) -> None:
        result = render_body(description="Just a description")
        assert result == "### Description\nJust a description"

    def test_only_story_id(self) -> None:
        result = render_body(story_id="S-042")
        assert result == "**Story**: S-042"

    def test_only_epic_id(self) -> None:
        result = render_body(epic_id="E-007")
        assert result == "**Epic**: E-007"

    def test_acceptance_criteria_without_description(self) -> None:
        ac = [AcceptanceCriterion(text="Works", done=False)]
        result = render_body(acceptance_criteria=ac)
        assert "### Acceptance Criteria" in result
        assert "- [ ] Works" in result
        assert "### Description" not in result

    def test_multiple_spec_refs(self) -> None:
        result = render_body(spec_refs=["a.md#x", "b.md#y", "c.md#z"])
        assert "**Spec refs**: a.md#x, b.md#y, c.md#z" in result


# ── parse_body ────────────────────────────────────────────────────────


class TestParseBody:
    def test_full_parse(self, full_body_text: str) -> None:
        parsed = parse_body(full_body_text)
        assert parsed["story_id"] == "S-001"
        assert parsed["spec_refs"] == ["orders.md#entities", "orders.md#error-scenarios"]
        assert parsed["dependencies"] == ["T-001", "T-003"]
        assert parsed["test_strategy"] == "Unit tests for domain validation"
        assert parsed["description"] == "Implement the order aggregate root with validation."
        assert len(parsed["acceptance_criteria"]) == 2
        assert parsed["acceptance_criteria"][0].text == "Order entity validates required fields"
        assert parsed["acceptance_criteria"][0].done is False
        assert parsed["acceptance_criteria"][1].text == "Invalid orders raise DomainError"
        assert parsed["acceptance_criteria"][1].done is True

    def test_empty_body(self) -> None:
        parsed = parse_body("")
        assert parsed["story_id"] is None
        assert parsed["spec_refs"] == []
        assert parsed["dependencies"] == []
        assert parsed["description"] == ""
        assert parsed["acceptance_criteria"] == []

    def test_description_only(self) -> None:
        body = "### Description\nSome text here"
        parsed = parse_body(body)
        assert parsed["description"] == "Some text here"
        assert parsed["story_id"] is None

    def test_epic_id_field(self) -> None:
        body = "**Epic**: E-010\n\n### Description\nEpic body"
        parsed = parse_body(body)
        assert parsed["epic_id"] == "E-010"
        assert parsed["description"] == "Epic body"

    def test_acceptance_criteria_mixed_states(self) -> None:
        body = "### Acceptance Criteria\n- [ ] Not done\n- [x] Done\n- [X] Also done (uppercase X)"
        parsed = parse_body(body)
        criteria = parsed["acceptance_criteria"]
        assert len(criteria) == 3
        assert criteria[0].done is False
        assert criteria[1].done is True
        assert criteria[2].done is True

    def test_unknown_fields_ignored(self) -> None:
        body = "**Story**: S-001\n**Random**: whatever\n### Description\nHello"
        parsed = parse_body(body)
        assert parsed["story_id"] == "S-001"
        assert parsed["description"] == "Hello"

    def test_multiline_description(self) -> None:
        body = "### Description\nLine 1\nLine 2\nLine 3"
        parsed = parse_body(body)
        assert parsed["description"] == "Line 1\nLine 2\nLine 3"


# ── Round-trip ────────────────────────────────────────────────────────


class TestRoundTrip:
    def test_full_round_trip(self, full_body_fields: dict) -> None:
        """render -> parse should recover the same structured data."""
        rendered = render_body(**full_body_fields)
        parsed = parse_body(rendered)
        assert parsed["story_id"] == full_body_fields["story_id"]
        assert parsed["spec_refs"] == full_body_fields["spec_refs"]
        assert parsed["dependencies"] == full_body_fields["dependencies"]
        assert parsed["test_strategy"] == full_body_fields["test_strategy"]
        assert parsed["description"] == full_body_fields["description"]
        assert len(parsed["acceptance_criteria"]) == len(full_body_fields["acceptance_criteria"])
        for original, recovered in zip(
            full_body_fields["acceptance_criteria"], parsed["acceptance_criteria"], strict=True
        ):
            assert recovered.text == original.text
            assert recovered.done == original.done

    def test_minimal_round_trip(self) -> None:
        """Minimal fields survive the round trip."""
        rendered = render_body(story_id="S-100", description="Tiny task")
        parsed = parse_body(rendered)
        assert parsed["story_id"] == "S-100"
        assert parsed["description"] == "Tiny task"
        assert parsed["dependencies"] == []

    def test_epic_round_trip(self) -> None:
        rendered = render_body(epic_id="E-005", description="Big picture")
        parsed = parse_body(rendered)
        assert parsed["epic_id"] == "E-005"
        assert parsed["description"] == "Big picture"

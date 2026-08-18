"""Tests for memory models — negative knowledge and provenance tracking."""

from __future__ import annotations

from ydk.models.memory import ExtractedMemoryModel


class TestAbandonedType:
    """ExtractedMemoryModel accepts 'abandoned' as a memory type."""

    def test_abandoned_type_accepted(self) -> None:
        mem = ExtractedMemoryModel(
            memory_type="abandoned",
            content="Tried Redis for session storage, rejected due to operational complexity",
        )
        assert mem.memory_type == "abandoned"

    def test_reason_field_for_abandoned(self) -> None:
        mem = ExtractedMemoryModel(
            memory_type="abandoned",
            content="Tried GraphQL, rejected in favor of REST",
            reason="GraphQL added complexity without sufficient query flexibility gains for our use case",
        )
        assert mem.reason == "GraphQL added complexity without sufficient query flexibility gains for our use case"

    def test_reason_defaults_to_empty(self) -> None:
        mem = ExtractedMemoryModel(memory_type="discovery", content="Found something")
        assert mem.reason == ""


class TestProvenanceFields:
    """ExtractedMemoryModel has source_type and verified fields."""

    def test_source_type_defaults_to_llm_extracted(self) -> None:
        mem = ExtractedMemoryModel(memory_type="discovery", content="Found X")
        assert mem.source_type == "llm-extracted"

    def test_verified_defaults_to_false(self) -> None:
        mem = ExtractedMemoryModel(memory_type="discovery", content="Found X")
        assert mem.verified is False

    def test_source_type_user_stated(self) -> None:
        mem = ExtractedMemoryModel(
            memory_type="decision",
            content="Use PostgreSQL",
            source_type="user-stated",
            verified=True,
        )
        assert mem.source_type == "user-stated"
        assert mem.verified is True

    def test_source_type_agent_discovered(self) -> None:
        mem = ExtractedMemoryModel(
            memory_type="pattern",
            content="Factory pattern used throughout",
            source_type="agent-discovered",
        )
        assert mem.source_type == "agent-discovered"

    def test_source_type_verified_value(self) -> None:
        mem = ExtractedMemoryModel(
            memory_type="gotcha",
            content="Watch out for X",
            source_type="verified",
        )
        assert mem.source_type == "verified"

    def test_source_type_unverified_value(self) -> None:
        mem = ExtractedMemoryModel(
            memory_type="gotcha",
            content="Watch out for X",
            source_type="unverified",
        )
        assert mem.source_type == "unverified"

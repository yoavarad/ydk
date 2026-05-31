"""Tests for Gate model validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from odk.models.gate import Gate, GateStatus, GateType


class TestGateType:
    def test_values(self) -> None:
        assert GateType.PR_MERGED == "pr-merged"
        assert GateType.CI_PASSED == "ci-passed"
        assert GateType.TIMER == "timer"
        assert GateType.HUMAN == "human"
        assert GateType.CUSTOM == "custom"

    def test_is_str_enum(self) -> None:
        assert isinstance(GateType.PR_MERGED, str)


class TestGateStatus:
    def test_values(self) -> None:
        assert GateStatus.PENDING == "pending"
        assert GateStatus.RESOLVED == "resolved"
        assert GateStatus.FAILED == "failed"


class TestGate:
    def test_minimal(self) -> None:
        g = Gate(id="G-001", type=GateType.HUMAN, description="Manager approval")
        assert g.id == "G-001"
        assert g.type == GateType.HUMAN
        assert g.status == GateStatus.PENDING
        assert g.config == {}
        assert g.resolved_at is None

    def test_full(self) -> None:
        g = Gate(
            id="G-002",
            type=GateType.PR_MERGED,
            description="Wait for API PR",
            status=GateStatus.RESOLVED,
            config={"pr_url": "https://github.com/org/repo/pull/42"},
            resolved_at="2025-06-01T12:00:00Z",
        )
        assert g.status == GateStatus.RESOLVED
        assert g.config["pr_url"] == "https://github.com/org/repo/pull/42"

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            Gate(id="G-001", type=GateType.HUMAN, description="x", bogus="bad")

    def test_rejects_invalid_type(self) -> None:
        with pytest.raises(ValidationError):
            Gate(id="G-001", type="invalid-type", description="x")

    def test_serialization_roundtrip(self) -> None:
        g = Gate(id="G-005", type=GateType.CUSTOM, description="Custom check", config={"key": "value"})
        data = g.model_dump()
        restored = Gate.model_validate(data)
        assert restored == g

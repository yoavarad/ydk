"""Tests for the named trigger registry and trigger event model."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ydk.core.trigger_registry import TriggerRegistry
from ydk.models.trigger import TriggerEvent, validate_trigger_id
from ydk.models.verification import CheckResult


class FakeHandler:
    """Minimal TriggerHandler implementation for tests."""

    def __init__(self, name: str, trigger: str, *, passed: bool = True) -> None:
        self._name = name
        self._trigger = trigger
        self._passed = passed
        self.run_count = 0

    @property
    def name(self) -> str:
        """Handler name."""
        return self._name

    @property
    def trigger(self) -> str:
        """Trigger ID."""
        return self._trigger

    async def run(self, context: dict[str, Any]) -> CheckResult:
        """Execute handler."""
        self.run_count += 1
        return CheckResult(
            name=self._name,
            passed=self._passed,
            output="ok" if self._passed else "FAILED",
            duration_seconds=0.0,
        )


class TestTriggerIdValidation:
    """Trigger ID format validation."""

    def test_valid_ids(self) -> None:
        """Accept valid namespace:name format."""
        assert validate_trigger_id("git:pre-commit") == "git:pre-commit"
        assert validate_trigger_id("git:pre-push") == "git:pre-push"

    def test_missing_namespace(self) -> None:
        """Reject IDs without namespace."""
        with pytest.raises(ValueError, match="Invalid trigger ID"):
            validate_trigger_id("pre-commit")

    def test_empty_string(self) -> None:
        """Reject empty string."""
        with pytest.raises(ValueError, match="Invalid trigger ID"):
            validate_trigger_id("")

    def test_uppercase_rejected(self) -> None:
        """Reject uppercase characters."""
        with pytest.raises(ValueError, match="Invalid trigger ID"):
            validate_trigger_id("Git:Pre-Commit")


class TestTriggerEvent:
    """TriggerEvent creation."""

    def test_create_sets_fields(self) -> None:
        """Factory sets all fields correctly."""
        event = TriggerEvent.create("git:pre-commit", {"project_root": "/tmp"})
        assert event.trigger_id == "git:pre-commit"
        assert event.context == {"project_root": "/tmp"}
        assert len(event.id) == 12

    def test_create_default_context(self) -> None:
        """Default context is empty dict."""
        event = TriggerEvent.create("git:pre-push")
        assert event.context == {}

    def test_invalid_trigger_id_rejected(self) -> None:
        """Invalid trigger ID raises ValueError."""
        with pytest.raises(ValueError, match="Invalid trigger ID"):
            TriggerEvent.create("bad")


class TestTriggerRegistryBasic:
    """TriggerRegistry register/get/list operations."""

    def test_register_and_get_handler(self) -> None:
        """Register a handler and retrieve it."""
        registry = TriggerRegistry()
        handler = FakeHandler("lint", "git:pre-commit")
        registry.register_handler("git:pre-commit", handler)
        assert len(registry.get_handlers("git:pre-commit")) == 1

    def test_get_handlers_empty(self) -> None:
        """Empty registry returns empty list."""
        assert TriggerRegistry().get_handlers("git:pre-commit") == []

    def test_list_triggers(self) -> None:
        """List triggers returns sorted IDs."""
        registry = TriggerRegistry()
        registry.register_handler("git:pre-push", FakeHandler("tests", "git:pre-push"))
        registry.register_handler("git:pre-commit", FakeHandler("lint", "git:pre-commit"))
        assert registry.list_triggers() == ["git:pre-commit", "git:pre-push"]

    def test_register_invalid_trigger_id(self) -> None:
        """Invalid trigger ID rejected on register."""
        with pytest.raises(ValueError, match="Invalid trigger ID"):
            TriggerRegistry().register_handler("bad-id", FakeHandler("lint", "bad-id"))


class TestTriggerRegistryEmit:
    """TriggerRegistry emit operations."""

    def test_emit_runs_all_handlers(self) -> None:
        """Emit runs all registered handlers."""
        registry = TriggerRegistry()
        h1 = FakeHandler("lint", "git:pre-commit")
        h2 = FakeHandler("types", "git:pre-commit")
        registry.register_handler("git:pre-commit", h1)
        registry.register_handler("git:pre-commit", h2)
        results = asyncio.run(registry.emit("git:pre-commit", {"project_root": "/tmp"}))
        assert len(results) == 2
        assert h1.run_count == 1

    def test_emit_no_handlers_returns_empty(self) -> None:
        """Emit with no handlers returns empty list."""
        assert asyncio.run(TriggerRegistry().emit("git:pre-commit")) == []

    def test_emit_invalid_trigger_id(self) -> None:
        """Emit with invalid trigger ID raises ValueError."""
        with pytest.raises(ValueError, match="Invalid trigger ID"):
            asyncio.run(TriggerRegistry().emit("bad"))

"""Named trigger registry with event-sourcing semantics."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from odk.models.trigger import TriggerEvent, validate_trigger_id

if TYPE_CHECKING:
    from odk.models.verification import CheckResult


@runtime_checkable
class TriggerHandler(Protocol):
    """Protocol that verification handlers must satisfy."""

    @property
    def name(self) -> str:
        """Handler name."""
        ...

    @property
    def trigger(self) -> str:
        """Trigger ID this handler responds to."""
        ...

    async def run(self, context: dict[str, Any]) -> CheckResult:
        """Execute the handler and return a check result."""
        ...


class TriggerRegistry:
    """Registry mapping trigger IDs to handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[TriggerHandler]] = defaultdict(list)

    def register_handler(self, trigger_id: str, handler: TriggerHandler) -> None:
        """Register a handler for a trigger ID."""
        validate_trigger_id(trigger_id)
        self._handlers[trigger_id].append(handler)

    def get_handlers(self, trigger_id: str) -> list[TriggerHandler]:
        """Return all handlers registered for *trigger_id*."""
        return list(self._handlers.get(trigger_id, []))

    def list_triggers(self) -> list[str]:
        """Return all registered trigger IDs (sorted)."""
        return sorted(self._handlers.keys())

    async def emit(self, trigger_id: str, context: dict[str, Any] | None = None) -> list[CheckResult]:
        """Fire a trigger: run all handlers in parallel, return results."""
        validate_trigger_id(trigger_id)
        event = TriggerEvent.create(trigger_id, context)
        handlers = self.get_handlers(trigger_id)
        if not handlers:
            return []
        results = await asyncio.gather(*(h.run(event.context) for h in handlers))
        return list(results)

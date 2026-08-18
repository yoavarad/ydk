"""General-purpose async event system.

Fire-and-forget event bus — handlers run in background daemon threads.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass
class Event:
    """Base event carrying a UTC timestamp."""

    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


@dataclass
class TaskStartedEvent(Event):
    """Emitted when a task transitions to in-progress."""

    task_id: str = ""
    summary: str = ""


@dataclass
class TaskPlanPostedEvent(Event):
    """Emitted when an implementation plan is posted to a task."""

    task_id: str = ""
    plan: str = ""


@dataclass
class TaskProgressEvent(Event):
    """Emitted on incremental progress updates."""

    task_id: str = ""
    message: str = ""


@dataclass
class TaskBlockedEvent(Event):
    """Emitted when a task becomes blocked."""

    task_id: str = ""
    reason: str = ""  # "code" or "decision"
    detail: str = ""


@dataclass
class TaskDoneEvent(Event):
    """Emitted when a task completes with verification proof."""

    task_id: str = ""
    pr_url: str = ""
    proof_path: str = ""


class EventBus:
    """General-purpose async event bus. Fire-and-forget — handlers run in background threads."""

    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable[..., object]]] = {}

    def register(self, event_type: type, handler: Callable[..., object]) -> None:
        """Register a handler for a specific event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    def emit(self, event: Event) -> None:
        """Fire all handlers for this event type in background threads."""
        for handler in self._handlers.get(type(event), []):
            threading.Thread(target=handler, args=(event,), daemon=True).start()

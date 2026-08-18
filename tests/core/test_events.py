"""Tests for ydk.core.events — EventBus and event types."""

from __future__ import annotations

import threading
import time

from ydk.core.events import (
    Event,
    EventBus,
    TaskBlockedEvent,
    TaskDoneEvent,
    TaskPlanPostedEvent,
    TaskProgressEvent,
    TaskStartedEvent,
)


def test_event_has_timestamp() -> None:
    """Event dataclass populates timestamp on creation."""
    e = Event()
    assert e.timestamp
    assert "T" in e.timestamp


def test_event_bus_register_handler() -> None:
    """EventBus.register stores handler for the given event type."""
    bus = EventBus()
    called = []
    bus.register(TaskStartedEvent, lambda e: called.append(e))
    # Handler stored but not called yet
    assert len(called) == 0


def test_event_bus_emits_to_registered_handlers() -> None:
    """EventBus.emit invokes handlers registered for the event type."""
    bus = EventBus()
    received: list[TaskStartedEvent] = []
    done_flag = threading.Event()

    def handler(event: TaskStartedEvent) -> None:
        received.append(event)
        done_flag.set()

    bus.register(TaskStartedEvent, handler)
    bus.emit(TaskStartedEvent(task_id="T-001", summary="hello"))

    done_flag.wait(timeout=2.0)
    assert len(received) == 1
    assert received[0].task_id == "T-001"


def test_event_bus_no_handlers_does_not_crash() -> None:
    """Emitting an event with no registered handlers is a no-op."""
    bus = EventBus()
    bus.emit(TaskStartedEvent(task_id="T-001"))
    # No exception raised


def test_event_bus_fire_and_forget_non_blocking() -> None:
    """Handlers run in daemon threads and don't block emit()."""
    bus = EventBus()
    barrier = threading.Event()

    def slow_handler(event: Event) -> None:
        barrier.wait(timeout=5.0)  # Blocks until we release

    bus.register(TaskStartedEvent, slow_handler)

    start = time.time()
    bus.emit(TaskStartedEvent(task_id="T-001"))
    elapsed = time.time() - start

    # emit() should return nearly instantly
    assert elapsed < 0.5

    # Release the handler so the daemon thread can exit cleanly
    barrier.set()


def test_event_bus_multiple_handlers_same_type() -> None:
    """Multiple handlers registered for the same event type all fire."""
    bus = EventBus()
    results: list[str] = []
    done_count = threading.Event()
    lock = threading.Lock()
    count = 0

    def make_handler(name: str):  # type: ignore[no-untyped-def]
        def handler(event: Event) -> None:
            nonlocal count
            with lock:
                results.append(name)
                count += 1
                if count >= 2:
                    done_count.set()

        return handler

    bus.register(TaskStartedEvent, make_handler("handler-a"))
    bus.register(TaskStartedEvent, make_handler("handler-b"))
    bus.emit(TaskStartedEvent(task_id="T-001"))

    done_count.wait(timeout=2.0)
    assert "handler-a" in results
    assert "handler-b" in results


def test_event_bus_different_event_types() -> None:
    """Handlers only fire for their registered event type."""
    bus = EventBus()
    started_events: list[Event] = []
    progress_events: list[Event] = []
    done_flag = threading.Event()

    def started_handler(event: Event) -> None:
        started_events.append(event)
        done_flag.set()

    def progress_handler(event: Event) -> None:
        progress_events.append(event)

    bus.register(TaskStartedEvent, started_handler)
    bus.register(TaskProgressEvent, progress_handler)

    bus.emit(TaskStartedEvent(task_id="T-001"))

    done_flag.wait(timeout=2.0)
    assert len(started_events) == 1
    assert len(progress_events) == 0


def test_task_event_dataclasses() -> None:
    """All task event dataclasses can be instantiated with their fields."""
    e1 = TaskStartedEvent(task_id="T-001", summary="hello")
    assert e1.task_id == "T-001"

    e2 = TaskPlanPostedEvent(task_id="T-001", plan="do stuff")
    assert e2.plan == "do stuff"

    e3 = TaskProgressEvent(task_id="T-001", message="halfway")
    assert e3.message == "halfway"

    e4 = TaskBlockedEvent(task_id="T-001", reason="code", detail="broken")
    assert e4.reason == "code"

    e5 = TaskDoneEvent(task_id="T-001", pr_url="http://x", proof_path="/tmp/proof")
    assert e5.pr_url == "http://x"

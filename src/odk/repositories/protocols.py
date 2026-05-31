"""Repository protocols (interfaces) for task/story/epic management.

STUB: Minimal protocol definitions. The other agent may expand these.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import builtins

    from odk.models.compaction import CompactedTask
    from odk.models.gate import Gate
    from odk.models.pm import (
        DependencyStatus,
        EpicCreate,
        EpicDetail,
        StoryCreate,
        StoryDetail,
        TaskCreate,
        TaskDetail,
    )


class TaskRepository(Protocol):
    """Create / read / update tasks on a remote issue tracker."""

    def create(self, task: TaskCreate) -> TaskDetail:
        """Create a new task and return its detail."""
        ...

    def get(self, issue_number: int) -> TaskDetail:
        """Retrieve a task by its issue number."""
        ...

    def list(
        self,
        milestone: str | None = None,
        labels: builtins.list[str] | None = None,
        status: str = "open",
    ) -> builtins.list[TaskDetail]:
        """List tasks filtered by milestone, labels, or status."""
        ...

    def update_status(self, issue_number: int, status: str) -> None:
        """Update a task's status."""
        ...

    def add_comment(self, issue_number: int, comment: str) -> None:
        """Append a comment to a task."""
        ...


class LifecycleTaskRepository(Protocol):
    """Extended task repository with lifecycle operations (assign, label, deps)."""

    def get_task(self, task_id: str) -> TaskDetail:
        """Retrieve a task by its string identifier."""
        ...

    def create_task(self, task: TaskCreate) -> TaskDetail:
        """Create a new task and return its detail."""
        ...

    def update_status(self, task_id: str, status: str) -> None:
        """Update a task's lifecycle status."""
        ...

    def add_comment(self, task_id: str, comment: str) -> None:
        """Append a comment to a task."""
        ...

    def assign(self, task_id: str, assignee: str) -> None:
        """Assign a task to a user."""
        ...

    def add_label(self, task_id: str, label: str) -> None:
        """Add a label to a task."""
        ...

    def remove_label(self, task_id: str, label: str) -> None:
        """Remove a label from a task."""
        ...

    def task_exists(self, task_id: str) -> bool:
        """Check if a task ID is valid and exists."""
        ...

    def check_dependencies(self, task_id: str) -> builtins.list[DependencyStatus]:
        """Return dependency statuses for a task."""
        ...

    def list_tasks(self, state: str = "open") -> builtins.list:
        """List tasks, optionally filtered by state."""
        ...

    def update_gates(self, task_id: str, gates: builtins.list[Gate]) -> None:
        """Persist updated gates for *task_id*."""
        ...

    def list_ready(self) -> builtins.list:
        """Return all open tasks whose blocking dependencies are satisfied."""
        ...

    def compact_task(self, task_id: str) -> CompactedTask:
        """Compact a completed task into a context-efficient summary."""
        ...

    def compact_all_done(self, *, dry_run: bool = False) -> builtins.list[str]:
        """Compact all done/closed tasks. Returns list of compacted IDs."""
        ...

    def update_frontmatter(self, task_id: str, fields: dict[str, object]) -> None:
        """Merge *fields* into the task's frontmatter and persist."""
        ...


class StoryRepository(Protocol):
    """Create / read / update stories on a remote issue tracker.

    The lifecycle-compatible methods (``create_story``, ``list_stories``)
    are what the CLI and factory actually call. Backends must implement
    these methods. The ``create``/``get``/``list`` methods are the
    lower-level CRUD interface used directly by some backends.
    """

    def create_story(self, story: StoryCreate) -> StoryDetail:
        """Create a new story and return its detail."""
        ...

    def list_stories(self, epic_id: str | None = None) -> builtins.list:
        """List stories, optionally filtered by epic."""
        ...


class EpicRepository(Protocol):
    """Create / read / update epics on a remote issue tracker.

    The lifecycle-compatible method (``create_epic``) is what the CLI
    and factory actually call.
    """

    def create_epic(self, epic: EpicCreate) -> EpicDetail:
        """Create a new epic and return its detail."""
        ...

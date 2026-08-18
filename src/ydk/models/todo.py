"""Models for the TODO management system."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class TodoStatus(StrEnum):
    """Status of a TODO item."""

    OPEN = "open"
    IN_PROGRESS = "in-progress"
    DONE = "done"


class TodoItem(BaseModel):
    """A single TODO tracking a NotImplementedError placeholder."""

    model_config = ConfigDict(extra="forbid")

    id: str
    file: str
    line: int
    method: str
    component_refs: list[str] = []
    status: TodoStatus = TodoStatus.OPEN
    task_id: str | None = None
    description: str = ""


class TodoRegistry(BaseModel):
    """Registry of all tracked TODOs, persisted to YAML."""

    model_config = ConfigDict(extra="forbid")

    todos: dict[str, TodoItem] = {}
    next_id: int = 1

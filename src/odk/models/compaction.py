"""Models for task compaction -- compressed summaries of completed tasks."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CompactedTask(BaseModel):
    """A compacted representation of a completed task.

    Preserves essential information (what was done, key decisions) while
    discarding verbose implementation detail and intermediate progress.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    status: str
    summary: str
    key_decisions: list[str]
    files_modified: list[str]
    original_description: str
    compacted_at: str

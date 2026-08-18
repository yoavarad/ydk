"""Buffer management models for sprint health tracking."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class BufferZone(StrEnum):
    """Sprint health zone based on buffer consumption."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class BufferStatus(BaseModel):
    """Aggregate sprint health derived from buffer consumption."""

    model_config = ConfigDict(extra="forbid")

    total_tasks: int
    completed_tasks: int
    in_progress_tasks: int
    blocked_tasks: int
    planned_waves: int
    elapsed_waves: int
    buffer_consumption_pct: float
    zone: BufferZone
    on_track: bool
    summary: str

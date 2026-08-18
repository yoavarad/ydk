"""Models for intelligent navigation (status enhancement)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ProjectStage(StrEnum):
    """Detected YDK project stage based on artifacts present."""

    EMPTY = "empty"
    INITIALIZED = "initialized"
    SPECIFIED = "specified"
    TASKED = "tasked"
    IN_PROGRESS = "in-progress"
    REVIEWING = "reviewing"


class ComponentCoverage(BaseModel):
    """Component coverage statistics."""

    model_config = ConfigDict(extra="forbid")

    total: int = 0
    referenced_by_tasks: int = 0
    orphaned: int = 0


class NavigationStatus(BaseModel):
    """Full navigation status for ydk status --navigate."""

    model_config = ConfigDict(extra="forbid")

    stage: ProjectStage
    next_action: str
    spec_count: int = 0
    adr_count: int = 0
    component_count: int = 0
    task_counts: dict[str, int] = Field(default_factory=dict)
    story_count: int = 0
    epic_count: int = 0
    component_coverage: ComponentCoverage | None = None

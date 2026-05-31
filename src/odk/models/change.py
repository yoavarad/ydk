"""Models for the spec evolution / change management system."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ChangeMode(StrEnum):
    """Change complexity mode."""

    MAJOR = "major"
    SMALL = "small"


class ChangeStatus(StrEnum):
    """Lifecycle state of a change."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class DeltaType(StrEnum):
    """Type of delta operation parsed from a delta spec."""

    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"


class DeltaOperation(BaseModel):
    """A single parsed delta operation from a delta spec file."""

    model_config = ConfigDict(extra="forbid")

    delta_type: DeltaType
    target_file: str
    section_heading: str
    content: str


class ChangeInfo(BaseModel):
    """Metadata about a change proposal."""

    model_config = ConfigDict(extra="forbid")

    name: str
    mode: ChangeMode
    status: ChangeStatus = ChangeStatus.ACTIVE
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    artifacts: dict[str, bool] = Field(default_factory=dict)


class ArtifactStatus(BaseModel):
    """Which artifacts are present and which are required for a change."""

    model_config = ConfigDict(extra="forbid")

    present: list[str] = Field(default_factory=list)
    required: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class ArchiveResult(BaseModel):
    """Result of archiving a change."""

    model_config = ConfigDict(extra="forbid")

    operations_applied: int
    target_files_modified: list[str] = Field(default_factory=list)
    archive_path: str

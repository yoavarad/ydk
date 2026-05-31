"""Models for checkpoint review guides."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BlastRadiusSpot(BaseModel):
    """A high blast-radius spot that deserves careful review."""

    model_config = ConfigDict(extra="forbid")

    location: str
    risk: str
    suggestion: str


class ReviewConcern(BaseModel):
    """A group of changes organized by what they affect, not what file they are in."""

    model_config = ConfigDict(extra="forbid")

    concern: str
    files: list[str] = Field(default_factory=list)
    summary: str


class CheckpointPreview(BaseModel):
    """Structured review guide for a git diff."""

    model_config = ConfigDict(extra="forbid")

    intent: str
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0
    concerns: list[ReviewConcern] = Field(default_factory=list)
    blast_radius: list[BlastRadiusSpot] = Field(default_factory=list)
    testing_suggestions: list[str] = Field(default_factory=list)

"""Models for memory consolidation — duplicate detection and health reporting."""

from pydantic import BaseModel, ConfigDict, Field


class DuplicateGroup(BaseModel):
    """A group of semantically similar memory entries."""

    model_config = ConfigDict(extra="forbid")

    canonical_id: str
    duplicate_ids: list[str] = Field(default_factory=list)
    similarity: float = Field(ge=0.0, le=1.0)
    topic: str = ""


class ConsolidationResult(BaseModel):
    """Result of consolidating duplicates for a single topic."""

    model_config = ConfigDict(extra="forbid")

    topic: str
    groups_found: int
    duplicates_merged: int
    kept_ids: list[str] = Field(default_factory=list)
    removed_ids: list[str] = Field(default_factory=list)


class ConsolidationReport(BaseModel):
    """Health report on the memory store."""

    model_config = ConfigDict(extra="forbid")

    total_memories: int
    duplicate_count: int
    stale_count: int
    groups: list[DuplicateGroup] = Field(default_factory=list)

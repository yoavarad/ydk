"""Memory extraction models -- Pydantic schemas for extracted memories and reports."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, computed_field

# Category weights by memory type (higher = more valuable to surface)
_CATEGORY_WEIGHTS: dict[str, float] = {
    "abandoned": 0.9,
    "decision": 0.85,
    "gotcha": 0.8,
    "pattern": 0.7,
    "discovery": 0.6,
    "convention": 0.5,
}

_DEFAULT_CATEGORY_WEIGHT = 0.5


class ExtractedMemoryModel(BaseModel):
    """A single memory extracted from a development session."""

    model_config = ConfigDict(extra="forbid")

    memory_type: str  # discovery, decision, gotcha, pattern, convention, abandoned
    content: str
    related_files: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    importance: str = "medium"
    task_id: str = ""
    extracted_at: str = ""
    reason: str = ""  # Why an approach was abandoned (primarily for 'abandoned' type)
    source_type: str = "llm-extracted"  # user-stated | llm-extracted | agent-discovered | verified | unverified
    verified: bool = False
    valid_from: str | None = None
    valid_until: str | None = None


class ExtractionReport(BaseModel):
    """Summary report of a memory extraction run."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    source: str  # "transcript" or "activity_log"
    memories: list[ExtractedMemoryModel]
    total_extracted: int
    timestamp: str


class MemoryScore(BaseModel):
    """4-factor ranking score for a memory result.

    Weighted sum: category*0.50 + provenance*0.15 + recency*0.25 + access*0.10
    """

    model_config = ConfigDict(extra="forbid")

    category_weight: float = Field(ge=0.0, le=1.0)
    provenance_score: float = Field(ge=0.0, le=1.0)
    recency_score: float = Field(ge=0.0, le=1.0)
    access_score: float = Field(ge=0.0, le=1.0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> float:
        """Weighted sum of the four factors."""
        return (
            self.category_weight * 0.50
            + self.provenance_score * 0.15
            + self.recency_score * 0.25
            + self.access_score * 0.10
        )

    @staticmethod
    def category_weight_for(memory_type: str) -> float:
        """Return the category weight for a given memory type."""
        return _CATEGORY_WEIGHTS.get(memory_type, _DEFAULT_CATEGORY_WEIGHT)

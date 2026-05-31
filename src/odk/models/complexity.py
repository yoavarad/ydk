"""Complexity scoring models for LLM-based task analysis."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ComplexityScore(BaseModel):
    """Result of LLM complexity analysis for a single task."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    score: int = Field(ge=1, le=10)
    reasoning: str
    should_expand: bool = False
    suggested_splits: list[str] = Field(default_factory=list)

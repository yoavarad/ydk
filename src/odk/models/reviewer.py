"""Pydantic models for the reviewer agent system."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReviewerConfigModel(BaseModel):
    """Serializable reviewer configuration (for config files and custom reviewers)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    group: str = "quality"
    system_prompt: str
    tool_names: list[str] = Field(default_factory=list)
    threshold: int = Field(default=8, ge=0, le=10)


class ReviewResultModel(BaseModel):
    """Serializable result from a single reviewer agent."""

    model_config = ConfigDict(extra="forbid")

    reviewer_id: str
    name: str
    score: int = Field(ge=0, le=10)
    passed: bool
    reasoning: str
    suggestions: list[str] = Field(default_factory=list)
    findings: list[dict[str, object]] = Field(default_factory=list)


class ReviewReport(BaseModel):
    """Aggregated report from all reviewer agents."""

    model_config = ConfigDict(extra="forbid")

    results: list[ReviewResultModel]
    passed: bool
    failed_reviewers: list[str] = Field(default_factory=list)
    average_score: float = 0.0
    llm_available: bool = True

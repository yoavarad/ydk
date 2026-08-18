"""Models for quick dev fast path."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class QuickDevContext(BaseModel):
    """Context produced by the quick dev setup for a coding agent."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    branch: str
    description: str
    components: list[str] = Field(default_factory=list)
    testing_guidance: str = ""

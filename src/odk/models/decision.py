"""Decision model -- first-class versioned decisions."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Decision(BaseModel):
    """A versioned decision on a specific topic."""

    model_config = ConfigDict(extra="forbid")

    topic: str
    content: str
    rationale: str
    version: int = Field(ge=1, default=1)
    created_at: str = ""
    supersedes: str | None = None

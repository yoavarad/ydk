"""External event gate models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class GateType(StrEnum):
    """Type of external event."""

    PR_MERGED = "pr-merged"
    CI_PASSED = "ci-passed"
    TIMER = "timer"
    HUMAN = "human"
    CUSTOM = "custom"


class GateStatus(StrEnum):
    """Current state of a gate."""

    PENDING = "pending"
    RESOLVED = "resolved"
    FAILED = "failed"


class Gate(BaseModel):
    """An external event gate."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: GateType
    description: str
    status: GateStatus = GateStatus.PENDING
    config: dict[str, str] = Field(default_factory=dict)
    resolved_at: str | None = None

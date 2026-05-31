"""Verification proof models."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class CheckResult(BaseModel):
    """Outcome of a single verification check including proof output."""

    model_config = ConfigDict(extra="forbid")
    name: str
    passed: bool
    output: str  # Raw command output (the proof)
    duration_seconds: float
    detail: dict[str, Any] | None = None  # Extra data (test_count, etc.)


class VerificationReport(BaseModel):
    """Full verification report aggregating all check results."""

    model_config = ConfigDict(extra="forbid")
    task_id: str | None = None
    timestamp: str
    checks: list[CheckResult]
    all_passed: bool
    total_duration_seconds: float

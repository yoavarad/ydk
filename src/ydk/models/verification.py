"""Verification proof models."""

from collections.abc import Iterable
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


def is_skipped(check: CheckResult) -> bool:
    """True when a check self-reported a skip (detail.status SKIPPED or legacy detail.skipped)."""
    detail = check.detail or {}
    return detail.get("status") == "SKIPPED" or (check.passed and detail.get("skipped") is True)


# A check waiting on subagent LLM responses; detail.request_paths lists the request files (ADR 0004).
NEEDS_LLM = "NEEDS_LLM"


def is_needs_llm(check: CheckResult) -> bool:
    """True when a check is waiting on subagent LLM responses (detail.status NEEDS_LLM)."""
    return (check.detail or {}).get("status") == NEEDS_LLM


def needs_llm_requests(checks: Iterable[CheckResult]) -> list[str]:
    """Request paths of every NEEDS_LLM check, in order, each path once."""
    paths: list[str] = []
    for check in checks:
        if is_needs_llm(check):
            paths.extend(p for p in (check.detail or {}).get("request_paths", []) if p not in paths)
    return paths


class VerificationReport(BaseModel):
    """Full verification report aggregating all check results."""

    model_config = ConfigDict(extra="forbid")
    task_id: str | None = None
    timestamp: str
    checks: list[CheckResult]
    all_passed: bool
    total_duration_seconds: float

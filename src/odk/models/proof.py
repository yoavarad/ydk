"""Proof capture data models."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

from pydantic import BaseModel, ConfigDict, Field


class ProofArtifacts(BaseModel):
    """Paths to all captured proof artifacts for a task."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    verification_report_path: Path | None = None
    plugin_outputs: dict[str, Path] = Field(default_factory=dict)
    screenshots: list[Path] = Field(default_factory=list)
    videos: list[Path] = Field(default_factory=list)
    summary_path: Path | None = None


class ProofStatus(BaseModel):
    """Aggregated pass/fail status from proof artifacts."""

    model_config = ConfigDict(extra="forbid")

    all_passed: bool
    failed_checks: list[str] = []

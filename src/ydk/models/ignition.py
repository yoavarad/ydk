"""Pydantic models for the ignition engine."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GeneratedFile(BaseModel):
    """A single file produced by an ignition generator."""

    model_config = ConfigDict(extra="forbid")

    path: str  # relative to project root
    content: str


class IgnitionResult(BaseModel):
    """Summary of a complete ignition run."""

    model_config = ConfigDict(extra="forbid")

    files_generated: int
    files_written: int  # may be less if hash unchanged
    files_skipped: int  # unchanged from previous ignition
    todos_registered: int
    errors: list[str]
    warnings: list[str]
    duration_seconds: float
    dependencies_installed: list[str] = []

"""Models for test generation and coverage reporting."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GeneratedTest(BaseModel):
    """A single generated test file."""

    model_config = ConfigDict(extra="forbid")

    component_id: str
    test_code: str
    test_file_path: str
    test_count: int


class CoverageByType(BaseModel):
    """Coverage statistics for a single component type."""

    model_config = ConfigDict(extra="forbid")

    type_name: str
    count: int
    covered: int
    pct: float


class CoverageReport(BaseModel):
    """Aggregate test coverage report across all component types."""

    model_config = ConfigDict(extra="forbid")

    total_components: int
    covered: int
    uncovered: int
    coverage_pct: float
    uncovered_ids: list[str]
    by_type: list[CoverageByType]

"""Models for test generation and coverage reporting."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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


class ManifestCoverage(BaseModel):
    """Implemented vs missing cases for one ydk:test manifest."""

    model_config = ConfigDict(extra="forbid")

    manifest_id: str
    level: str = ""
    implemented: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class CoverageReport(BaseModel):
    """Aggregate test coverage report across all component types."""

    model_config = ConfigDict(extra="forbid")

    total_components: int
    covered: int
    uncovered: int
    coverage_pct: float
    uncovered_ids: list[str]
    by_type: list[CoverageByType]
    manifests: list[ManifestCoverage] = Field(default_factory=list)
    req_cases: dict[str, list[str]] = Field(default_factory=dict)
    reqs_without_cases: list[str] = Field(default_factory=list)

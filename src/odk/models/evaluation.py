"""Models for evaluation results (spec-check and future enforcement gates)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from odk.models.component import LinkerResult, ScannerResult


class CriterionResult(BaseModel):
    """Score and reasoning for a single evaluation criterion."""

    model_config = ConfigDict(extra="forbid")

    criterion_id: str
    score: float = Field(ge=0, le=10)
    passed: bool
    reasoning: str
    suggestions: list[str] = Field(default_factory=list)


class EvalReport(BaseModel):
    """Aggregated report of all criterion evaluations for a spec-check run."""

    model_config = ConfigDict(extra="forbid")

    spec_files: list[str]
    timestamp: str
    overall: Literal["PASS", "FAIL"]
    average_score: float
    criteria_results: list[CriterionResult]
    failed_criteria: list[str]
    execution: dict[str, Any]


class ComponentFinding(BaseModel):
    """A single finding from deterministic component quality checks."""

    model_config = ConfigDict(extra="forbid")

    component_id: str
    file_path: str
    check: str
    severity: str  # "error" | "warning"
    message: str
    suggestion: str


class SpecVerificationReport(BaseModel):
    """Combined report from all verification phases."""

    model_config = ConfigDict(extra="forbid")

    component_findings: list[ComponentFinding]
    linker_result: LinkerResult
    narrative_scores: list[CriterionResult]
    scanner_result: ScannerResult
    passed: bool
    summary: str

"""Tests for ydk.models — Pydantic data models."""

import pytest
from pydantic import ValidationError

from ydk.models import (
    CriterionResult,
    CustomCriterion,
    DagValidationResult,
    EvalReport,
    ExecutionConfig,
    HooksConfig,
    ProjectConfig,
    SpecCheckConfig,
    SpecCheckThresholds,
    Task,
    TaskManagementConfig,
    YdkConfig,
)

# --- YdkConfig ---


class TestYdkConfig:
    def test_validates_with_all_defaults(self) -> None:
        """Only project.name is required; everything else has defaults."""
        cfg = YdkConfig(project=ProjectConfig(name="my-project"))
        assert cfg.project.name == "my-project"
        assert cfg.project.spec_location == "docs/specs"
        assert cfg.hooks == HooksConfig()
        assert cfg.spec_check == SpecCheckConfig()
        assert cfg.task_management == TaskManagementConfig()
        assert cfg.execution == ExecutionConfig()

    def test_rejects_unknown_fields_on_ydk_config(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            YdkConfig(project=ProjectConfig(name="x"), bogus="nope")

    def test_rejects_unknown_fields_on_project_config(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            ProjectConfig(name="x", unknown_field="bad")

    def test_rejects_unknown_fields_on_hooks_config(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            HooksConfig(unknown="bad")

    def test_rejects_unknown_fields_on_spec_check_config(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            SpecCheckConfig(unknown="bad")

    def test_rejects_invalid_threshold_too_high(self) -> None:
        with pytest.raises(ValidationError):
            SpecCheckThresholds(completeness=11)

    def test_rejects_invalid_threshold_too_low(self) -> None:
        with pytest.raises(ValidationError):
            SpecCheckThresholds(clarity=-1)

    def test_remote_literal(self) -> None:
        p = ProjectConfig(name="x", remote="gitlab")
        assert p.remote == "gitlab"
        with pytest.raises(ValidationError):
            ProjectConfig(name="x", remote="bitbucket")

    def test_config_round_trip(self) -> None:
        """create -> dump -> reload -> equal."""
        cfg = YdkConfig(
            project=ProjectConfig(name="roundtrip", remote="gitlab"),
            spec_check=SpecCheckConfig(timeout=90, thresholds=SpecCheckThresholds(completeness=5)),
        )
        data = cfg.model_dump()
        reloaded = YdkConfig.model_validate(data)
        assert reloaded == cfg


# --- CustomCriterion ---


class TestCustomCriterion:
    def test_validates_all_required_fields(self) -> None:
        c = CustomCriterion(id="c1", rubric="test rubric", name="Test", prompt="Check X", threshold=7)
        assert c.id == "c1"
        assert c.threshold == 7

    def test_missing_required_field(self) -> None:
        with pytest.raises(ValidationError):
            CustomCriterion(id="c1", rubric="r")  # missing name, prompt, threshold

    def test_rejects_threshold_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            CustomCriterion(id="c1", rubric="r", name="n", prompt="p", threshold=11)


# --- CriterionResult ---


class TestCriterionResult:
    def test_validates_score_range(self) -> None:
        r = CriterionResult(criterion_id="c1", score=8.5, passed=True, reasoning="Good")
        assert r.score == 8.5

    def test_rejects_score_above_10(self) -> None:
        with pytest.raises(ValidationError):
            CriterionResult(criterion_id="c1", score=10.1, passed=True, reasoning="x")

    def test_rejects_score_below_0(self) -> None:
        with pytest.raises(ValidationError):
            CriterionResult(criterion_id="c1", score=-0.1, passed=False, reasoning="x")


# --- EvalReport ---


class TestEvalReport:
    def test_overall_must_be_pass_or_fail(self) -> None:
        r = EvalReport(
            spec_files=["a.md"],
            timestamp="2026-01-01T00:00:00Z",
            overall="PASS",
            average_score=9.0,
            criteria_results=[],
            failed_criteria=[],
            execution={},
        )
        assert r.overall == "PASS"

    def test_rejects_invalid_overall(self) -> None:
        with pytest.raises(ValidationError):
            EvalReport(
                spec_files=[],
                timestamp="t",
                overall="MAYBE",
                average_score=5.0,
                criteria_results=[],
                failed_criteria=[],
                execution={},
            )


# --- Task ---


class TestTask:
    def test_empty_depends_on(self) -> None:
        t = Task(id="T-001", title="Setup")
        assert t.depends_on == []

    def test_with_dependencies(self) -> None:
        t = Task(id="T-002", title="Build", depends_on=["T-001"])
        assert t.depends_on == ["T-001"]


# --- DagValidationResult ---


class TestDagValidationResult:
    def test_cycles_none_means_no_cycles(self) -> None:
        d = DagValidationResult(
            valid=True,
            cycles=None,
            parallel_sets=[["T-001", "T-002"], ["T-003"]],
            critical_path=["T-001", "T-003"],
            critical_path_length=2,
            fan_out={"T-001": 2},
        )
        assert d.valid is True
        assert d.cycles is None

    def test_with_cycles(self) -> None:
        d = DagValidationResult(
            valid=False,
            cycles=["T-001 -> T-002 -> T-001"],
            parallel_sets=[],
            critical_path=[],
            critical_path_length=0,
            fan_out={},
        )
        assert d.valid is False
        assert d.cycles == ["T-001 -> T-002 -> T-001"]

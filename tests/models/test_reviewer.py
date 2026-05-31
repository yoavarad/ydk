"""Tests for reviewer Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from odk.models.reviewer import ReviewerConfigModel, ReviewReport, ReviewResultModel


class TestReviewerConfigModel:
    def test_valid_config(self):
        config = ReviewerConfigModel(
            id="N08",
            name="No Technical Specs in Prose",
            system_prompt="Check for technical specs.",
            tool_names=["scan_url_paths", "scan_type_annotations"],
            threshold=7,
            group="quality",
        )
        assert config.id == "N08"
        assert config.threshold == 7
        assert len(config.tool_names) == 2

    def test_defaults(self):
        config = ReviewerConfigModel(
            id="T01",
            name="Test",
            system_prompt="Test prompt.",
        )
        assert config.group == "quality"
        assert config.threshold == 8
        assert config.tool_names == []

    def test_threshold_bounds(self):
        with pytest.raises(ValidationError):
            ReviewerConfigModel(
                id="T01",
                name="Test",
                system_prompt="Test.",
                threshold=11,
            )

        with pytest.raises(ValidationError):
            ReviewerConfigModel(
                id="T01",
                name="Test",
                system_prompt="Test.",
                threshold=-1,
            )

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ReviewerConfigModel(
                id="T01",
                name="Test",
                system_prompt="Test.",
                unknown_field="bad",  # type: ignore[call-arg]
            )


class TestReviewResultModel:
    def test_valid_result(self):
        result = ReviewResultModel(
            reviewer_id="N08",
            name="No Technical Specs in Prose",
            score=9,
            passed=True,
            reasoning="Clean narrative.",
            suggestions=["Minor tweak possible."],
            findings=[{"line": 5, "text": "minor", "issue": "small"}],
        )
        assert result.score == 9
        assert result.passed is True
        assert len(result.findings) == 1

    def test_defaults(self):
        result = ReviewResultModel(
            reviewer_id="N01",
            name="Problem Statement",
            score=8,
            passed=True,
            reasoning="Good.",
        )
        assert result.suggestions == []
        assert result.findings == []

    def test_score_bounds(self):
        with pytest.raises(ValidationError):
            ReviewResultModel(
                reviewer_id="N01",
                name="Test",
                score=11,
                passed=True,
                reasoning="Bad.",
            )

    def test_serialization_roundtrip(self):
        result = ReviewResultModel(
            reviewer_id="N05",
            name="Ambiguity",
            score=6,
            passed=False,
            reasoning="Several vague terms found.",
            suggestions=["Replace 'fast' with a specific latency target."],
            findings=[{"line": 10, "text": "fast", "category": "vague_term"}],
        )
        data = result.model_dump()
        restored = ReviewResultModel(**data)
        assert restored == result


class TestReviewReport:
    def test_valid_report(self):
        results = [
            ReviewResultModel(
                reviewer_id="N01",
                name="Problem Statement",
                score=9,
                passed=True,
                reasoning="Good.",
            ),
            ReviewResultModel(
                reviewer_id="N08",
                name="No Technical Specs",
                score=4,
                passed=False,
                reasoning="Technical specs found in prose.",
            ),
        ]
        report = ReviewReport(
            results=results,
            passed=False,
            failed_reviewers=["N08"],
            average_score=6.5,
            llm_available=True,
        )
        assert not report.passed
        assert report.failed_reviewers == ["N08"]
        assert report.average_score == 6.5

    def test_defaults(self):
        report = ReviewReport(
            results=[],
            passed=True,
        )
        assert report.failed_reviewers == []
        assert report.average_score == 0.0
        assert report.llm_available is True

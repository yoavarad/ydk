"""Tests for LLM-scored task complexity analysis."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from odk.core.complexity_scorer import ComplexityScorer, LLMProvider, _build_prompt
from odk.models.complexity import ComplexityScore
from odk.models.pm import TaskDetail

# ---------------------------------------------------------------------------
# Mock LLM provider (system boundary — OK to mock)
# ---------------------------------------------------------------------------


class MockLLMProvider:
    """Returns a canned JSON response."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.last_prompt: str | None = None

    def invoke(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self._response


def _make_task(**overrides: object) -> TaskDetail:
    """Create a minimal TaskDetail for testing."""
    defaults: dict[str, object] = {
        "id": "T-001",
        "title": "Add user login",
        "description": "Implement login with JWT",
        "acceptance_criteria": ["Users can log in", "JWT tokens issued"],
        "dependencies": ["T-000"],
        "spec_refs": ["docs/specs/auth.md"],
    }
    defaults.update(overrides)
    return TaskDetail(**defaults)  # type: ignore[arg-type]


def _make_response(
    score: int = 6,
    reasoning: str = "Moderate complexity",
    should_expand: bool = False,
    suggested_splits: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            "score": score,
            "reasoning": reasoning,
            "should_expand": should_expand,
            "suggested_splits": suggested_splits or [],
        }
    )


# ---------------------------------------------------------------------------
# ComplexityScore model validation
# ---------------------------------------------------------------------------


class TestComplexityScoreModel:
    def test_valid_score(self) -> None:
        cs = ComplexityScore(task_id="T-001", score=7, reasoning="Complex task")
        assert cs.score == 7
        assert cs.should_expand is False
        assert cs.suggested_splits == []

    def test_score_below_1_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ComplexityScore(task_id="T-001", score=0, reasoning="Invalid")

    def test_score_above_10_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ComplexityScore(task_id="T-001", score=11, reasoning="Invalid")

    def test_should_expand_and_splits(self) -> None:
        cs = ComplexityScore(
            task_id="T-001",
            score=9,
            reasoning="Very complex",
            should_expand=True,
            suggested_splits=["Split A", "Split B"],
        )
        assert cs.should_expand is True
        assert len(cs.suggested_splits) == 2


# ---------------------------------------------------------------------------
# TaskDetail with complexity field
# ---------------------------------------------------------------------------


class TestTaskModelComplexity:
    def test_task_detail_has_complexity_field(self) -> None:
        task = TaskDetail(title="test", complexity=7, complexity_reasoning="Hard")
        assert task.complexity == 7
        assert task.complexity_reasoning == "Hard"

    def test_task_detail_complexity_defaults_none(self) -> None:
        task = TaskDetail(title="test")
        assert task.complexity is None
        assert task.complexity_reasoning is None


# ---------------------------------------------------------------------------
# Graceful skip without LLM provider
# ---------------------------------------------------------------------------


class TestNoProvider:
    def test_returns_default_score_5(self) -> None:
        scorer = ComplexityScorer(llm_provider=None)
        result = scorer.score_task(_make_task())
        assert result.score == 5
        assert "No LLM provider" in result.reasoning
        assert result.should_expand is False

    def test_batch_returns_defaults(self) -> None:
        scorer = ComplexityScorer(llm_provider=None)
        tasks = [_make_task(id="T-001"), _make_task(id="T-002")]
        results = scorer.score_tasks(tasks)
        assert len(results) == 2
        assert all(r.score == 5 for r in results)


# ---------------------------------------------------------------------------
# Scoring with mocked LLM provider
# ---------------------------------------------------------------------------


class TestScoring:
    def test_parses_valid_response(self) -> None:
        provider = MockLLMProvider(_make_response(score=8, reasoning="Cross-cutting", should_expand=True))
        scorer = ComplexityScorer(llm_provider=provider)
        result = scorer.score_task(_make_task())

        assert result.task_id == "T-001"
        assert result.score == 8
        assert result.reasoning == "Cross-cutting"
        assert result.should_expand is True

    def test_handles_code_fenced_json(self) -> None:
        inner = _make_response(score=3, reasoning="Simple")
        response = f"```json\n{inner}\n```"
        provider = MockLLMProvider(response)
        scorer = ComplexityScorer(llm_provider=provider)
        result = scorer.score_task(_make_task())
        assert result.score == 3

    def test_handles_malformed_json(self) -> None:
        provider = MockLLMProvider("not valid json")
        scorer = ComplexityScorer(llm_provider=provider)
        result = scorer.score_task(_make_task())
        assert result.score == 5
        assert "could not be parsed" in result.reasoning

    def test_clamps_score_to_range(self) -> None:
        provider = MockLLMProvider(_make_response(score=15))
        scorer = ComplexityScorer(llm_provider=provider)
        result = scorer.score_task(_make_task())
        assert result.score == 10

    def test_prompt_includes_task_fields(self) -> None:
        provider = MockLLMProvider(_make_response())
        scorer = ComplexityScorer(llm_provider=provider)
        scorer.score_task(_make_task())
        assert provider.last_prompt is not None
        assert "Add user login" in provider.last_prompt
        assert "JWT" in provider.last_prompt
        assert "T-000" in provider.last_prompt
        assert "docs/specs/auth.md" in provider.last_prompt

    def test_prompt_includes_context(self) -> None:
        provider = MockLLMProvider(_make_response())
        scorer = ComplexityScorer(llm_provider=provider)
        scorer.score_task(_make_task(), context="Sprint 3 focus area")
        assert provider.last_prompt is not None
        assert "Sprint 3 focus area" in provider.last_prompt

    def test_suggested_splits(self) -> None:
        response = _make_response(
            score=9,
            should_expand=True,
            suggested_splits=["Extract auth module", "Add JWT tests"],
        )
        provider = MockLLMProvider(response)
        scorer = ComplexityScorer(llm_provider=provider)
        result = scorer.score_task(_make_task())
        assert result.suggested_splits == ["Extract auth module", "Add JWT tests"]


# ---------------------------------------------------------------------------
# Batch scoring
# ---------------------------------------------------------------------------


class TestBatchScoring:
    def test_scores_all_tasks(self) -> None:
        provider = MockLLMProvider(_make_response(score=4))
        scorer = ComplexityScorer(llm_provider=provider)
        tasks = [_make_task(id="T-001"), _make_task(id="T-002"), _make_task(id="T-003")]
        results = scorer.score_tasks(tasks)
        assert len(results) == 3
        assert [r.task_id for r in results] == ["T-001", "T-002", "T-003"]

    def test_empty_list(self) -> None:
        provider = MockLLMProvider(_make_response())
        scorer = ComplexityScorer(llm_provider=provider)
        results = scorer.score_tasks([])
        assert results == []


# ---------------------------------------------------------------------------
# LLMProvider Protocol
# ---------------------------------------------------------------------------


class TestLLMProviderProtocol:
    def test_mock_satisfies_protocol(self) -> None:
        provider = MockLLMProvider("response")
        assert isinstance(provider, LLMProvider)


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_includes_acceptance_criteria(self) -> None:
        task = _make_task(acceptance_criteria=["Criterion A", "Criterion B"])
        prompt = _build_prompt(task)
        assert "Criterion A" in prompt
        assert "Criterion B" in prompt

    def test_no_context(self) -> None:
        prompt = _build_prompt(_make_task(), context=None)
        assert "Additional context" not in prompt

    def test_with_context(self) -> None:
        prompt = _build_prompt(_make_task(), context="Extra info")
        assert "Extra info" in prompt

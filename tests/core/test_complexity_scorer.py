"""Tests for LLM-scored task complexity analysis."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from ydk.core.complexity_scorer import ComplexityAssessment, ComplexityScorer, _build_prompt
from ydk.core.llm_provider import AnthropicLLMProvider, StructuredLLMProvider
from ydk.models.complexity import ComplexityScore
from ydk.models.pm import TaskDetail

# ---------------------------------------------------------------------------
# Fake anthropic SDK client (system boundary) behind the real provider
# ---------------------------------------------------------------------------


class FakeAnthropicClient:
    """Fake SDK client: ``messages.parse`` validates canned data into ``output_format``."""

    def __init__(self, data: dict[str, object]) -> None:
        self._data = data
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def parse(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=kwargs["output_format"].model_validate(self._data))

    @property
    def last_prompt(self) -> str:
        return self.calls[-1]["messages"][0]["content"]


def _provider(data: dict[str, object]) -> tuple[AnthropicLLMProvider, FakeAnthropicClient]:
    client = FakeAnthropicClient(data)
    return AnthropicLLMProvider(client=client, model_id="claude-sonnet-5"), client


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
) -> dict[str, object]:
    return {
        "score": score,
        "reasoning": reasoning,
        "should_expand": should_expand,
        "suggested_splits": suggested_splits or [],
    }


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
        provider, _ = _provider(_make_response(score=8, reasoning="Cross-cutting", should_expand=True))
        scorer = ComplexityScorer(llm_provider=provider)
        result = scorer.score_task(_make_task())

        assert result.task_id == "T-001"
        assert result.score == 8
        assert result.reasoning == "Cross-cutting"
        assert result.should_expand is True

    def test_request_uses_structured_output_without_sampling_or_tool_choice(self) -> None:
        provider, client = _provider(_make_response())
        ComplexityScorer(llm_provider=provider).score_task(_make_task())

        call = client.calls[-1]
        assert call["output_format"] is ComplexityAssessment
        assert "temperature" not in call
        assert "tool_choice" not in call

    def test_clamps_score_to_range(self) -> None:
        provider, _ = _provider(_make_response(score=15))
        scorer = ComplexityScorer(llm_provider=provider)
        result = scorer.score_task(_make_task())
        assert result.score == 10

    def test_prompt_includes_task_fields(self) -> None:
        provider, client = _provider(_make_response())
        scorer = ComplexityScorer(llm_provider=provider)
        scorer.score_task(_make_task())
        assert "Add user login" in client.last_prompt
        assert "JWT" in client.last_prompt
        assert "T-000" in client.last_prompt
        assert "docs/specs/auth.md" in client.last_prompt

    def test_prompt_includes_context(self) -> None:
        provider, client = _provider(_make_response())
        scorer = ComplexityScorer(llm_provider=provider)
        scorer.score_task(_make_task(), context="Sprint 3 focus area")
        assert "Sprint 3 focus area" in client.last_prompt

    def test_suggested_splits(self) -> None:
        response = _make_response(
            score=9,
            should_expand=True,
            suggested_splits=["Extract auth module", "Add JWT tests"],
        )
        provider, _ = _provider(response)
        scorer = ComplexityScorer(llm_provider=provider)
        result = scorer.score_task(_make_task())
        assert result.suggested_splits == ["Extract auth module", "Add JWT tests"]


# ---------------------------------------------------------------------------
# Batch scoring
# ---------------------------------------------------------------------------


class TestBatchScoring:
    def test_scores_all_tasks(self) -> None:
        provider, _ = _provider(_make_response(score=4))
        scorer = ComplexityScorer(llm_provider=provider)
        tasks = [_make_task(id="T-001"), _make_task(id="T-002"), _make_task(id="T-003")]
        results = scorer.score_tasks(tasks)
        assert len(results) == 3
        assert [r.task_id for r in results] == ["T-001", "T-002", "T-003"]

    def test_empty_list(self) -> None:
        provider, _ = _provider(_make_response())
        scorer = ComplexityScorer(llm_provider=provider)
        results = scorer.score_tasks([])
        assert results == []


# ---------------------------------------------------------------------------
# StructuredLLMProvider Protocol
# ---------------------------------------------------------------------------


class TestLLMProviderProtocol:
    def test_provider_satisfies_protocol(self) -> None:
        provider, _ = _provider(_make_response())
        assert isinstance(provider, StructuredLLMProvider)


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

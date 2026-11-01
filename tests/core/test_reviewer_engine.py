"""Unit tests for the cached fan-out reviewer engine.

Anthropic tests mock the anthropic SDK client (a system boundary) behind a real
``AnthropicLLMProvider``; subagent tests use a real ``SubagentProvider`` on tmp_path.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest

from ydk.core.claude_client import ClaudeAPIError
from ydk.core.llm_provider import AnthropicLLMProvider, SubagentHandoff, SubagentProvider, SubagentResponseError
from ydk.core.reviewer_engine import SYSTEM_PROMPT, ReviewerEngine, ReviewFinding, ReviewVerdict, spec_context

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_error() -> anthropic.AuthenticationError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.AuthenticationError("bad key", response=httpx.Response(401, request=request), body=None)


def _mock_converse_response(
    *,
    score: int = 8,
    reasoning: str = "Good",
    suggestions: list[str] | None = None,
    findings: list[dict] | None = None,
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read: int = 0,
    cache_write: int = 0,
) -> SimpleNamespace:
    """Build a fake ``messages.parse`` response carrying a parsed ReviewVerdict."""
    return SimpleNamespace(
        stop_reason="end_turn",
        parsed_output=ReviewVerdict(
            score=score,
            reasoning=reasoning,
            suggestions=suggestions or [],
            findings=[ReviewFinding(**f) for f in findings or []],
        ),
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_write,
        ),
    )


def _make_reviewers(count: int = 3, tier: str = "review") -> list[dict]:
    return [
        {
            "id": f"N{str(i + 1).zfill(2)}",
            "name": f"Reviewer {i + 1}",
            "system_prompt": f"Evaluate criterion {i + 1}.",
            "model_tier": tier,
            "threshold": 8,
            "group": "quality",
        }
        for i in range(count)
    ]


MODEL_TIERS = {
    "review": "claude-sonnet-4-6",
    "fast": "claude-haiku-4-5",
}


def _engine(client: MagicMock) -> ReviewerEngine:
    return ReviewerEngine(lambda tier: AnthropicLLMProvider(client=client, model_id=MODEL_TIERS[tier], max_tokens=8192))


def _subagent_engine(root: Path) -> ReviewerEngine:
    return ReviewerEngine(
        lambda tier: SubagentProvider(
            root, purpose="spec-review", model_tier=tier, model=MODEL_TIERS[tier], agent="general-purpose"
        )
    )


# ---------------------------------------------------------------------------
# Prompts (system instruction + cached spec context)
# ---------------------------------------------------------------------------


class TestPrompts:
    def test_spec_context_embeds_spec(self):
        assert "Hello World" in spec_context("Hello World")

    def test_anthropic_call_caches_spec_block(self):
        mock_client = MagicMock()
        mock_client.messages.parse.return_value = _mock_converse_response()

        _engine(mock_client).run_all("# My Spec", _make_reviewers(1))

        system = mock_client.messages.parse.call_args.kwargs["system"]
        assert system[0] == {"type": "text", "text": SYSTEM_PROMPT}
        assert system[1]["text"] == spec_context("# My Spec")
        assert system[1]["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# ReviewVerdict — structured output schema
# ---------------------------------------------------------------------------


class TestReviewVerdictSchema:
    def test_required_fields(self):
        schema = ReviewVerdict.model_json_schema()
        assert set(schema["required"]) == {"score", "reasoning", "suggestions", "findings"}

    def test_finding_has_line_text_issue(self):
        assert set(ReviewFinding.model_fields) == {"line", "text", "issue"}


# ---------------------------------------------------------------------------
# _call_reviewer — structured output
# ---------------------------------------------------------------------------


class TestCallReviewer:
    def test_extracts_structured_result(self):
        mock_client = MagicMock()
        mock_client.messages.parse.return_value = _mock_converse_response(
            score=9, reasoning="Excellent", suggestions=["Do X"], findings=[{"line": 1, "text": "foo", "issue": "bar"}]
        )

        engine = _engine(mock_client)
        result = engine._call_reviewer(engine._provider("review"), "# Spec", "N01", "Evaluate")

        assert result["reviewer_id"] == "N01"
        assert result["score"] == 9
        assert result["reasoning"] == "Excellent"
        assert result["suggestions"] == ["Do X"]
        assert len(result["findings"]) == 1
        assert result["findings"][0]["line"] == 1

    def test_request_uses_structured_output_without_sampling_or_tools(self):
        mock_client = MagicMock()
        mock_client.messages.parse.return_value = _mock_converse_response()

        engine = _engine(mock_client)
        engine._call_reviewer(engine._provider("review"), "# Spec", "N01", "Evaluate")

        call_kwargs = mock_client.messages.parse.call_args[1]
        assert call_kwargs["output_format"] is ReviewVerdict
        assert call_kwargs["max_tokens"] == 8192
        assert call_kwargs["system"][1]["cache_control"] == {"type": "ephemeral"}
        for absent in ("temperature", "tool_choice", "tools"):
            assert absent not in call_kwargs

    def test_missing_structured_output_raises(self):
        mock_client = MagicMock()
        mock_client.messages.parse.return_value = SimpleNamespace(stop_reason="refusal", parsed_output=None)

        engine = _engine(mock_client)
        with pytest.raises(ClaudeAPIError, match="no structured output"):
            engine._call_reviewer(engine._provider("review"), "# Spec", "N01", "Evaluate")

    def test_authentication_error_raises_not_score_zero(self):
        mock_client = MagicMock()
        mock_client.messages.parse.side_effect = _auth_error()

        engine = _engine(mock_client)
        with pytest.raises(ClaudeAPIError, match="invalid or missing API key"):
            engine._call_reviewer(engine._provider("review"), "# Spec", "N01", "Evaluate")


# ---------------------------------------------------------------------------
# run_all — mocked anthropic client
# ---------------------------------------------------------------------------


class TestRunAll:
    def test_basic_flow(self):
        mock_client = MagicMock()

        # First call: cache write; subsequent: cache read
        mock_client.messages.parse.side_effect = [
            _mock_converse_response(score=9, reasoning="Excellent", cache_write=5000),
            _mock_converse_response(score=7, reasoning="Decent", suggestions=["Improve X"], cache_read=5000),
            _mock_converse_response(score=8, reasoning="Good", cache_read=5000),
        ]

        engine = _engine(mock_client)
        results = engine.run_all(
            spec_content="# Test Spec",
            reviewers=_make_reviewers(3),
            max_workers=2,
        )

        assert len(results) == 3
        assert mock_client.messages.parse.call_count == 3
        # Results sorted by reviewer_id
        ids = [r["reviewer_id"] for r in results]
        assert ids == sorted(ids)

    def test_empty_reviewers(self):
        mock_client = MagicMock()

        engine = _engine(mock_client)
        results = engine.run_all("# Spec", [])
        assert results == []
        mock_client.messages.parse.assert_not_called()

    def test_authentication_error_propagates(self):
        mock_client = MagicMock()
        mock_client.messages.parse.side_effect = _auth_error()

        engine = _engine(mock_client)
        with pytest.raises(ClaudeAPIError, match="invalid or missing API key"):
            engine.run_all(
                spec_content="# Test",
                reviewers=_make_reviewers(1),
            )

    def test_authentication_error_in_fanout_propagates(self):
        mock_client = MagicMock()
        mock_client.messages.parse.side_effect = [_mock_converse_response(), _auth_error()]

        engine = _engine(mock_client)
        with pytest.raises(ClaudeAPIError, match="invalid or missing API key"):
            engine.run_all(
                spec_content="# Test",
                reviewers=_make_reviewers(2),
            )

    def test_model_tier_resolution(self):
        mock_client = MagicMock()

        mock_client.messages.parse.return_value = _mock_converse_response()

        engine = _engine(mock_client)
        reviewers = [
            {
                "id": "N01",
                "name": "Smart",
                "system_prompt": "Eval",
                "model_tier": "review",
                "threshold": 8,
                "group": "q",
            },
            {
                "id": "N02",
                "name": "Fast",
                "system_prompt": "Eval",
                "model_tier": "fast",
                "threshold": 7,
                "group": "q",
            },
        ]
        engine.run_all("# Spec", reviewers)

        # First call (prime) uses smart model
        first_call_kwargs = mock_client.messages.parse.call_args_list[0][1]
        assert first_call_kwargs["model"] == MODEL_TIERS["review"]

    def test_per_tier_cache_priming(self):
        """Each model tier should prime its own cache independently."""
        mock_client = MagicMock()

        call_order: list[tuple[str, str]] = []

        def track_calls(**kwargs):
            model_id = kwargs["model"]
            user_text = kwargs["messages"][0]["content"]
            call_order.append((model_id, user_text))
            return _mock_converse_response()

        mock_client.messages.parse.side_effect = track_calls

        engine = _engine(mock_client)
        reviewers = [
            {
                "id": "N01",
                "name": "Smart One",
                "system_prompt": "Smart eval 1",
                "model_tier": "review",
                "threshold": 8,
                "group": "q",
            },
            {
                "id": "N02",
                "name": "Smart Two",
                "system_prompt": "Smart eval 2",
                "model_tier": "review",
                "threshold": 8,
                "group": "q",
            },
            {
                "id": "N03",
                "name": "Fast One",
                "system_prompt": "Fast eval 1",
                "model_tier": "fast",
                "threshold": 7,
                "group": "q",
            },
            {
                "id": "N04",
                "name": "Fast Two",
                "system_prompt": "Fast eval 2",
                "model_tier": "fast",
                "threshold": 7,
                "group": "q",
            },
        ]
        engine.run_all("# Spec", reviewers)

        assert mock_client.messages.parse.call_count == 4

        # Verify smart-tier calls use Sonnet model
        smart_calls = [(m, t) for m, t in call_order if m == MODEL_TIERS["review"]]
        fast_calls = [(m, t) for m, t in call_order if m == MODEL_TIERS["fast"]]
        assert len(smart_calls) == 2
        assert len(fast_calls) == 2

        # First call per tier should be the primer (synchronous)
        # Smart tier primer is first overall
        assert call_order[0][0] == MODEL_TIERS["review"]
        assert call_order[0][1] == "Smart eval 1"

    def test_mixed_tiers_each_get_correct_model(self):
        """Reviewers with different tiers should each use their tier's model."""
        mock_client = MagicMock()

        models_used: dict[str, str] = {}

        def track_calls(**kwargs):
            model_id = kwargs["model"]
            user_text = kwargs["messages"][0]["content"]
            models_used[user_text] = model_id
            return _mock_converse_response()

        mock_client.messages.parse.side_effect = track_calls

        engine = _engine(mock_client)
        reviewers = [
            {
                "id": "N01",
                "name": "S",
                "system_prompt": "smart_prompt",
                "model_tier": "review",
                "threshold": 8,
                "group": "q",
            },
            {
                "id": "N02",
                "name": "F",
                "system_prompt": "fast_prompt",
                "model_tier": "fast",
                "threshold": 7,
                "group": "q",
            },
        ]
        engine.run_all("# Spec", reviewers)

        assert models_used["smart_prompt"] == MODEL_TIERS["review"]
        assert models_used["fast_prompt"] == MODEL_TIERS["fast"]

    def test_passed_threshold(self):
        mock_client = MagicMock()

        mock_client.messages.parse.return_value = _mock_converse_response(score=7)

        engine = _engine(mock_client)
        reviewers = [
            {
                "id": "N01",
                "name": "Test",
                "system_prompt": "Eval",
                "model_tier": "review",
                "threshold": 8,
                "group": "q",
            },
        ]
        results = engine.run_all("# Spec", reviewers)

        assert results[0]["passed"] is False  # 7 < 8

    def test_passed_at_threshold(self):
        mock_client = MagicMock()

        mock_client.messages.parse.return_value = _mock_converse_response(score=8)

        engine = _engine(mock_client)
        reviewers = [
            {
                "id": "N01",
                "name": "Test",
                "system_prompt": "Eval",
                "model_tier": "review",
                "threshold": 8,
                "group": "q",
            },
        ]
        results = engine.run_all("# Spec", reviewers)

        assert results[0]["passed"] is True  # 8 >= 8


class TestSubagentHandoff:
    def test_all_reviewers_collected_into_one_handoff(self, tmp_path: Path):
        with pytest.raises(SubagentHandoff) as exc:
            _subagent_engine(tmp_path).run_all("# Spec", _make_reviewers(3))

        assert len(exc.value.request_paths) == 3
        data = json.loads(exc.value.request_paths[0].read_text(encoding="utf-8"))
        assert data["system"] == SYSTEM_PROMPT
        assert data["cacheable_context"] == spec_context("# Spec")

    def test_rerun_with_responses_completes(self, tmp_path: Path):
        with pytest.raises(SubagentHandoff) as exc:
            _subagent_engine(tmp_path).run_all("# Spec", _make_reviewers(3))
        responses = tmp_path / "responses"
        responses.mkdir()
        verdict = {"score": 9, "reasoning": "ok", "suggestions": [], "findings": []}
        for path in exc.value.request_paths:
            (responses / path.name).write_text(json.dumps(verdict), encoding="utf-8")

        results = _subagent_engine(tmp_path).run_all("# Spec", _make_reviewers(3))

        assert [r["reviewer_id"] for r in results] == ["N01", "N02", "N03"]
        assert all(r["score"] == 9 and r["passed"] for r in results)

    def test_invalid_fanout_response_fails_loudly(self, tmp_path: Path):
        with pytest.raises(SubagentHandoff) as exc:
            _subagent_engine(tmp_path).run_all("# Spec", _make_reviewers(2))
        responses = tmp_path / "responses"
        responses.mkdir()
        good = {"score": 9, "reasoning": "ok", "suggestions": [], "findings": []}
        first, second = sorted(exc.value.request_paths, key=lambda q: json.loads(q.read_text("utf-8"))["user"])
        (responses / first.name).write_text(json.dumps(good), encoding="utf-8")
        (responses / second.name).write_text("{}", encoding="utf-8")

        with pytest.raises(SubagentResponseError):
            _subagent_engine(tmp_path).run_all("# Spec", _make_reviewers(2))

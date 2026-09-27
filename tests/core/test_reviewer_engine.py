"""Unit tests for the cached fan-out reviewer engine.

All tests mock the anthropic client — no real Anthropic API calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest

from ydk.core.claude_client import ClaudeAPIError, MissingCredentialsError
from ydk.core.reviewer_engine import REVIEW_TOOL_SPEC, ReviewerEngine

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
    """Build a mock Anthropic Messages API response with a tool_use block."""
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                input={
                    "score": score,
                    "reasoning": reasoning,
                    "suggestions": suggestions or [],
                    "findings": findings or [],
                },
            )
        ],
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_write,
        ),
    )


def _make_reviewers(count: int = 3, tier: str = "smart") -> list[dict]:
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
    "smart": "claude-sonnet-4-6",
    "fast": "claude-haiku-4-5",
}


# ---------------------------------------------------------------------------
# _build_system_blocks
# ---------------------------------------------------------------------------


class TestBuildSystemBlocks:
    def test_structure_has_cache_point(self):
        engine = ReviewerEngine.__new__(ReviewerEngine)
        blocks = engine._build_system_blocks("# My Spec\nSome content")

        assert len(blocks) == 2
        assert "text" in blocks[0]
        assert "text" in blocks[1]
        assert blocks[1]["cache_control"] == {"type": "ephemeral"}

    def test_spec_content_embedded(self):
        engine = ReviewerEngine.__new__(ReviewerEngine)
        blocks = engine._build_system_blocks("Hello World")

        assert "Hello World" in blocks[1]["text"]


# ---------------------------------------------------------------------------
# REVIEW_TOOL_SPEC
# ---------------------------------------------------------------------------


class TestReviewToolSpec:
    def test_tool_spec_structure(self):
        assert REVIEW_TOOL_SPEC["name"] == "submit_review"
        schema = REVIEW_TOOL_SPEC["input_schema"]
        assert set(schema["required"]) == {"score", "reasoning", "suggestions", "findings"}

    def test_findings_schema_has_line_text_issue(self):
        findings_items = REVIEW_TOOL_SPEC["input_schema"]["properties"]["findings"]["items"]
        assert "line" in findings_items["properties"]
        assert "text" in findings_items["properties"]
        assert "issue" in findings_items["properties"]


# ---------------------------------------------------------------------------
# _call_reviewer — tool_use extraction
# ---------------------------------------------------------------------------


class TestCallReviewer:
    def test_extracts_tooluse_result(self):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_converse_response(
            score=9, reasoning="Excellent", suggestions=["Do X"], findings=[{"line": 1, "text": "foo", "issue": "bar"}]
        )

        engine = ReviewerEngine(client=mock_client)
        system_blocks = engine._build_system_blocks("# Spec")
        result = engine._call_reviewer(system_blocks, MODEL_TIERS["smart"], "N01", "Evaluate")

        assert result["reviewer_id"] == "N01"
        assert result["score"] == 9
        assert result["reasoning"] == "Excellent"
        assert result["suggestions"] == ["Do X"]
        assert len(result["findings"]) == 1
        assert result["findings"][0]["line"] == 1

    def test_passes_tool_config(self):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_converse_response()

        engine = ReviewerEngine(client=mock_client)
        system_blocks = engine._build_system_blocks("# Spec")
        engine._call_reviewer(system_blocks, MODEL_TIERS["smart"], "N01", "Evaluate")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["tool_choice"] == {"type": "tool", "name": "submit_review"}
        assert call_kwargs["max_tokens"] == 8192

    def test_missing_tooluse_block_returns_zero(self):
        mock_client = MagicMock()
        # Response with text instead of tool_use (shouldn't happen, but handle gracefully)
        mock_client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="oops")],
            usage=SimpleNamespace(
                input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0
            ),
        )

        engine = ReviewerEngine(client=mock_client)
        system_blocks = engine._build_system_blocks("# Spec")
        result = engine._call_reviewer(system_blocks, MODEL_TIERS["smart"], "N01", "Evaluate")

        assert result["score"] == 0
        assert "No tool_use block" in result["reasoning"]

    def test_authentication_error_raises_not_score_zero(self):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _auth_error()

        engine = ReviewerEngine(client=mock_client)
        system_blocks = engine._build_system_blocks("# Spec")
        with pytest.raises(ClaudeAPIError, match="invalid or missing API key"):
            engine._call_reviewer(system_blocks, MODEL_TIERS["smart"], "N01", "Evaluate")


# ---------------------------------------------------------------------------
# run_all — mocked anthropic client
# ---------------------------------------------------------------------------


class TestRunAll:
    def test_basic_flow(self):
        mock_client = MagicMock()

        # First call: cache write; subsequent: cache read
        mock_client.messages.create.side_effect = [
            _mock_converse_response(score=9, reasoning="Excellent", cache_write=5000),
            _mock_converse_response(score=7, reasoning="Decent", suggestions=["Improve X"], cache_read=5000),
            _mock_converse_response(score=8, reasoning="Good", cache_read=5000),
        ]

        engine = ReviewerEngine(client=mock_client)
        results = engine.run_all(
            spec_content="# Test Spec",
            reviewers=_make_reviewers(3),
            model_tiers=MODEL_TIERS,
            max_workers=2,
        )

        assert len(results) == 3
        assert mock_client.messages.create.call_count == 3
        # Results sorted by reviewer_id
        ids = [r["reviewer_id"] for r in results]
        assert ids == sorted(ids)

    def test_empty_reviewers(self):
        mock_client = MagicMock()

        engine = ReviewerEngine(client=mock_client)
        results = engine.run_all("# Spec", [], MODEL_TIERS)
        assert results == []
        mock_client.messages.create.assert_not_called()

    def test_authentication_error_propagates(self):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _auth_error()

        engine = ReviewerEngine(client=mock_client)
        with pytest.raises(ClaudeAPIError, match="invalid or missing API key"):
            engine.run_all(
                spec_content="# Test",
                reviewers=_make_reviewers(1),
                model_tiers=MODEL_TIERS,
            )

    def test_authentication_error_in_fanout_propagates(self):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [_mock_converse_response(), _auth_error()]

        engine = ReviewerEngine(client=mock_client)
        with pytest.raises(ClaudeAPIError, match="invalid or missing API key"):
            engine.run_all(
                spec_content="# Test",
                reviewers=_make_reviewers(2),
                model_tiers=MODEL_TIERS,
            )

    def test_model_tier_resolution(self):
        mock_client = MagicMock()

        mock_client.messages.create.return_value = _mock_converse_response()

        engine = ReviewerEngine(client=mock_client)
        reviewers = [
            {
                "id": "N01",
                "name": "Smart",
                "system_prompt": "Eval",
                "model_tier": "smart",
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
        engine.run_all("# Spec", reviewers, MODEL_TIERS)

        # First call (prime) uses smart model
        first_call_kwargs = mock_client.messages.create.call_args_list[0][1]
        assert first_call_kwargs["model"] == MODEL_TIERS["smart"]

    def test_per_tier_cache_priming(self):
        """Each model tier should prime its own cache independently."""
        mock_client = MagicMock()

        call_order: list[tuple[str, str]] = []

        def track_calls(**kwargs):
            model_id = kwargs["model"]
            user_text = kwargs["messages"][0]["content"]
            call_order.append((model_id, user_text))
            return _mock_converse_response()

        mock_client.messages.create.side_effect = track_calls

        engine = ReviewerEngine(client=mock_client)
        reviewers = [
            {
                "id": "N01",
                "name": "Smart One",
                "system_prompt": "Smart eval 1",
                "model_tier": "smart",
                "threshold": 8,
                "group": "q",
            },
            {
                "id": "N02",
                "name": "Smart Two",
                "system_prompt": "Smart eval 2",
                "model_tier": "smart",
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
        engine.run_all("# Spec", reviewers, MODEL_TIERS)

        assert mock_client.messages.create.call_count == 4

        # Verify smart-tier calls use Sonnet model
        smart_calls = [(m, t) for m, t in call_order if m == MODEL_TIERS["smart"]]
        fast_calls = [(m, t) for m, t in call_order if m == MODEL_TIERS["fast"]]
        assert len(smart_calls) == 2
        assert len(fast_calls) == 2

        # First call per tier should be the primer (synchronous)
        # Smart tier primer is first overall
        assert call_order[0][0] == MODEL_TIERS["smart"]
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

        mock_client.messages.create.side_effect = track_calls

        engine = ReviewerEngine(client=mock_client)
        reviewers = [
            {
                "id": "N01",
                "name": "S",
                "system_prompt": "smart_prompt",
                "model_tier": "smart",
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
        engine.run_all("# Spec", reviewers, MODEL_TIERS)

        assert models_used["smart_prompt"] == MODEL_TIERS["smart"]
        assert models_used["fast_prompt"] == MODEL_TIERS["fast"]

    def test_passed_threshold(self):
        mock_client = MagicMock()

        mock_client.messages.create.return_value = _mock_converse_response(score=7)

        engine = ReviewerEngine(client=mock_client)
        reviewers = [
            {"id": "N01", "name": "Test", "system_prompt": "Eval", "model_tier": "smart", "threshold": 8, "group": "q"},
        ]
        results = engine.run_all("# Spec", reviewers, MODEL_TIERS)

        assert results[0]["passed"] is False  # 7 < 8

    def test_passed_at_threshold(self):
        mock_client = MagicMock()

        mock_client.messages.create.return_value = _mock_converse_response(score=8)

        engine = ReviewerEngine(client=mock_client)
        reviewers = [
            {"id": "N01", "name": "Test", "system_prompt": "Eval", "model_tier": "smart", "threshold": 8, "group": "q"},
        ]
        results = engine.run_all("# Spec", reviewers, MODEL_TIERS)

        assert results[0]["passed"] is True  # 8 >= 8


class TestConstruction:
    def test_missing_credentials_raise_at_construction(self, monkeypatch):
        monkeypatch.delenv("YDK_TEST_MISSING_KEY", raising=False)
        with pytest.raises(MissingCredentialsError):
            ReviewerEngine(api_key_env="YDK_TEST_MISSING_KEY")

    def test_builds_client_from_custom_env(self, monkeypatch):
        monkeypatch.setenv("YDK_TEST_KEY", "sk-test")
        engine = ReviewerEngine(api_key_env="YDK_TEST_KEY")
        assert engine._client.api_key == "sk-test"

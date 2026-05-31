"""Unit tests for the cached fan-out reviewer engine.

All tests mock the boto3 client — no real Bedrock calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from odk.core.reviewer_engine import REVIEW_TOOL_SPEC, ReviewerEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
) -> dict:
    """Build a mock Bedrock Converse response with a toolUse block."""
    return {
        "output": {
            "message": {
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "mock-id",
                            "name": "submit_review",
                            "input": {
                                "score": score,
                                "reasoning": reasoning,
                                "suggestions": suggestions or [],
                                "findings": findings or [],
                            },
                        }
                    }
                ],
            },
        },
        "usage": {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "cacheReadInputTokens": cache_read,
            "cacheWriteInputTokens": cache_write,
        },
    }


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
    "smart": "us.anthropic.claude-sonnet-4-6-v1:0",
    "fast": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
}


# ---------------------------------------------------------------------------
# _build_system_blocks
# ---------------------------------------------------------------------------


class TestBuildSystemBlocks:
    def test_structure_has_cache_point(self):
        engine = ReviewerEngine.__new__(ReviewerEngine)
        blocks = engine._build_system_blocks("# My Spec\nSome content")

        assert len(blocks) == 3
        assert "text" in blocks[0]
        assert "text" in blocks[1]
        assert blocks[2] == {"cachePoint": {"type": "default"}}

    def test_spec_content_embedded(self):
        engine = ReviewerEngine.__new__(ReviewerEngine)
        blocks = engine._build_system_blocks("Hello World")

        assert "Hello World" in blocks[1]["text"]


# ---------------------------------------------------------------------------
# REVIEW_TOOL_SPEC
# ---------------------------------------------------------------------------


class TestReviewToolSpec:
    def test_tool_spec_structure(self):
        assert "toolSpec" in REVIEW_TOOL_SPEC
        spec = REVIEW_TOOL_SPEC["toolSpec"]
        assert spec["name"] == "submit_review"
        schema = spec["inputSchema"]["json"]
        assert set(schema["required"]) == {"score", "reasoning", "suggestions", "findings"}

    def test_findings_schema_has_line_text_issue(self):
        findings_items = REVIEW_TOOL_SPEC["toolSpec"]["inputSchema"]["json"]["properties"]["findings"]["items"]
        assert "line" in findings_items["properties"]
        assert "text" in findings_items["properties"]
        assert "issue" in findings_items["properties"]


# ---------------------------------------------------------------------------
# _call_reviewer — toolUse extraction
# ---------------------------------------------------------------------------


class TestCallReviewer:
    @patch("odk.core.reviewer_engine.boto3")
    def test_extracts_tooluse_result(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.Session.return_value.client.return_value = mock_client
        mock_client.converse.return_value = _mock_converse_response(
            score=9, reasoning="Excellent", suggestions=["Do X"], findings=[{"line": 1, "text": "foo", "issue": "bar"}]
        )

        engine = ReviewerEngine(aws_profile="test", region="us-east-1")
        system_blocks = engine._build_system_blocks("# Spec")
        result = engine._call_reviewer(system_blocks, MODEL_TIERS["smart"], "N01", "Evaluate")

        assert result["reviewer_id"] == "N01"
        assert result["score"] == 9
        assert result["reasoning"] == "Excellent"
        assert result["suggestions"] == ["Do X"]
        assert len(result["findings"]) == 1
        assert result["findings"][0]["line"] == 1

    @patch("odk.core.reviewer_engine.boto3")
    def test_passes_tool_config(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.Session.return_value.client.return_value = mock_client
        mock_client.converse.return_value = _mock_converse_response()

        engine = ReviewerEngine(aws_profile="test", region="us-east-1")
        system_blocks = engine._build_system_blocks("# Spec")
        engine._call_reviewer(system_blocks, MODEL_TIERS["smart"], "N01", "Evaluate")

        call_kwargs = mock_client.converse.call_args[1]
        assert "toolConfig" in call_kwargs
        assert call_kwargs["toolConfig"]["toolChoice"] == {"tool": {"name": "submit_review"}}
        assert call_kwargs["inferenceConfig"]["maxTokens"] == 8192

    @patch("odk.core.reviewer_engine.boto3")
    def test_missing_tooluse_block_returns_zero(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.Session.return_value.client.return_value = mock_client
        # Response with text instead of toolUse (shouldn't happen, but handle gracefully)
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "oops"}]}},
            "usage": {"inputTokens": 10, "outputTokens": 5},
        }

        engine = ReviewerEngine(aws_profile="test", region="us-east-1")
        system_blocks = engine._build_system_blocks("# Spec")
        result = engine._call_reviewer(system_blocks, MODEL_TIERS["smart"], "N01", "Evaluate")

        assert result["score"] == 0
        assert "No toolUse block" in result["reasoning"]

    @patch("odk.core.reviewer_engine.boto3")
    def test_bedrock_exception_handled(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.Session.return_value.client.return_value = mock_client
        mock_client.converse.side_effect = Exception("Throttled")

        engine = ReviewerEngine(aws_profile="test", region="us-east-1")
        system_blocks = engine._build_system_blocks("# Spec")
        result = engine._call_reviewer(system_blocks, MODEL_TIERS["smart"], "N01", "Evaluate")

        assert result["score"] == 0
        assert "BEDROCK ERROR" in result["reasoning"]


# ---------------------------------------------------------------------------
# run_all — mocked boto3 client
# ---------------------------------------------------------------------------


class TestRunAll:
    @patch("odk.core.reviewer_engine.boto3")
    def test_basic_flow(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.Session.return_value.client.return_value = mock_client

        # First call: cache write; subsequent: cache read
        mock_client.converse.side_effect = [
            _mock_converse_response(score=9, reasoning="Excellent", cache_write=5000),
            _mock_converse_response(score=7, reasoning="Decent", suggestions=["Improve X"], cache_read=5000),
            _mock_converse_response(score=8, reasoning="Good", cache_read=5000),
        ]

        engine = ReviewerEngine(aws_profile="test", region="us-east-1")
        results = engine.run_all(
            spec_content="# Test Spec",
            reviewers=_make_reviewers(3),
            model_tiers=MODEL_TIERS,
            max_workers=2,
        )

        assert len(results) == 3
        assert mock_client.converse.call_count == 3
        # Results sorted by reviewer_id
        ids = [r["reviewer_id"] for r in results]
        assert ids == sorted(ids)

    @patch("odk.core.reviewer_engine.boto3")
    def test_empty_reviewers(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.Session.return_value.client.return_value = mock_client

        engine = ReviewerEngine()
        results = engine.run_all("# Spec", [], MODEL_TIERS)
        assert results == []
        mock_client.converse.assert_not_called()

    @patch("odk.core.reviewer_engine.boto3")
    def test_bedrock_error_handled(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.Session.return_value.client.return_value = mock_client

        mock_client.converse.side_effect = Exception("Throttled")

        engine = ReviewerEngine()
        results = engine.run_all(
            spec_content="# Test",
            reviewers=_make_reviewers(1),
            model_tiers=MODEL_TIERS,
        )

        assert len(results) == 1
        assert results[0]["score"] == 0
        assert "BEDROCK ERROR" in results[0]["reasoning"]

    @patch("odk.core.reviewer_engine.boto3")
    def test_model_tier_resolution(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.Session.return_value.client.return_value = mock_client

        mock_client.converse.return_value = _mock_converse_response()

        engine = ReviewerEngine()
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
        first_call_kwargs = mock_client.converse.call_args_list[0][1]
        assert first_call_kwargs["modelId"] == MODEL_TIERS["smart"]

    @patch("odk.core.reviewer_engine.boto3")
    def test_per_tier_cache_priming(self, mock_boto3):
        """Each model tier should prime its own cache independently."""
        mock_client = MagicMock()
        mock_boto3.Session.return_value.client.return_value = mock_client

        call_order: list[tuple[str, str]] = []

        def track_calls(**kwargs):
            model_id = kwargs["modelId"]
            user_text = kwargs["messages"][0]["content"][0]["text"]
            call_order.append((model_id, user_text))
            return _mock_converse_response()

        mock_client.converse.side_effect = track_calls

        engine = ReviewerEngine()
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

        assert mock_client.converse.call_count == 4

        # Verify smart-tier calls use Sonnet model
        smart_calls = [(m, t) for m, t in call_order if m == MODEL_TIERS["smart"]]
        fast_calls = [(m, t) for m, t in call_order if m == MODEL_TIERS["fast"]]
        assert len(smart_calls) == 2
        assert len(fast_calls) == 2

        # First call per tier should be the primer (synchronous)
        # Smart tier primer is first overall
        assert call_order[0][0] == MODEL_TIERS["smart"]
        assert call_order[0][1] == "Smart eval 1"

    @patch("odk.core.reviewer_engine.boto3")
    def test_mixed_tiers_each_get_correct_model(self, mock_boto3):
        """Reviewers with different tiers should each use their tier's model."""
        mock_client = MagicMock()
        mock_boto3.Session.return_value.client.return_value = mock_client

        models_used: dict[str, str] = {}

        def track_calls(**kwargs):
            model_id = kwargs["modelId"]
            user_text = kwargs["messages"][0]["content"][0]["text"]
            models_used[user_text] = model_id
            return _mock_converse_response()

        mock_client.converse.side_effect = track_calls

        engine = ReviewerEngine()
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

    @patch("odk.core.reviewer_engine.boto3")
    def test_passed_threshold(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.Session.return_value.client.return_value = mock_client

        mock_client.converse.return_value = _mock_converse_response(score=7)

        engine = ReviewerEngine()
        reviewers = [
            {"id": "N01", "name": "Test", "system_prompt": "Eval", "model_tier": "smart", "threshold": 8, "group": "q"},
        ]
        results = engine.run_all("# Spec", reviewers, MODEL_TIERS)

        assert results[0]["passed"] is False  # 7 < 8

    @patch("odk.core.reviewer_engine.boto3")
    def test_passed_at_threshold(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.Session.return_value.client.return_value = mock_client

        mock_client.converse.return_value = _mock_converse_response(score=8)

        engine = ReviewerEngine()
        reviewers = [
            {"id": "N01", "name": "Test", "system_prompt": "Eval", "model_tier": "smart", "threshold": 8, "group": "q"},
        ]
        results = engine.run_all("# Spec", reviewers, MODEL_TIERS)

        assert results[0]["passed"] is True  # 8 >= 8

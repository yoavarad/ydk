"""Tests for odk.core.extractor — LLM-based memory extraction."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from odk.core.extractor import ExtractedMemory, MemoryExtractor


class TestExtractedMemory:
    def test_dataclass_defaults(self) -> None:
        mem = ExtractedMemory(memory_type="discovery", content="X uses Y")
        assert mem.memory_type == "discovery"
        assert mem.content == "X uses Y"
        assert mem.related_files == []
        assert mem.concepts == []
        assert mem.importance == "medium"

    def test_dataclass_with_all_fields(self) -> None:
        mem = ExtractedMemory(
            memory_type="decision",
            content="Chose HS256 for JWT signing",
            related_files=["src/auth.py"],
            concepts=["trade-off", "why-it-exists"],
            importance="high",
        )
        assert mem.memory_type == "decision"
        assert len(mem.related_files) == 1
        assert "trade-off" in mem.concepts


class TestParseResponse:
    """Test the static _parse_response method independently."""

    def test_parses_valid_json_array(self) -> None:
        data = [
            {
                "memory_type": "discovery",
                "content": "AuthHandler uses HS256 algorithm",
                "related_files": ["src/api/auth.py"],
                "concepts": ["how-it-works"],
                "importance": "medium",
            }
        ]
        result = MemoryExtractor._parse_response(json.dumps(data))
        assert len(result) == 1
        assert result[0].memory_type == "discovery"
        assert result[0].content == "AuthHandler uses HS256 algorithm"
        assert result[0].related_files == ["src/api/auth.py"]

    def test_parses_json_wrapped_in_markdown_fences(self) -> None:
        data = [
            {
                "memory_type": "gotcha",
                "content": "Order matters",
                "related_files": [],
                "concepts": [],
                "importance": "high",
            }
        ]
        text = f"```json\n{json.dumps(data)}\n```"
        result = MemoryExtractor._parse_response(text)
        assert len(result) == 1
        assert result[0].memory_type == "gotcha"
        assert result[0].importance == "high"

    def test_returns_empty_for_garbage(self) -> None:
        assert MemoryExtractor._parse_response("not json at all") == []

    def test_returns_empty_for_empty_array(self) -> None:
        assert MemoryExtractor._parse_response("[]") == []

    def test_skips_items_without_content(self) -> None:
        data = [{"memory_type": "discovery", "content": ""}, {"memory_type": "discovery", "content": "Real content"}]
        result = MemoryExtractor._parse_response(json.dumps(data))
        assert len(result) == 1
        assert result[0].content == "Real content"

    def test_defaults_unknown_type_to_discovery(self) -> None:
        data = [
            {
                "memory_type": "bogus_type",
                "content": "Some finding",
                "related_files": [],
                "concepts": [],
                "importance": "medium",
            }
        ]
        result = MemoryExtractor._parse_response(json.dumps(data))
        assert len(result) == 1
        assert result[0].memory_type == "discovery"

    def test_defaults_unknown_importance_to_medium(self) -> None:
        data = [
            {
                "memory_type": "decision",
                "content": "A decision",
                "related_files": [],
                "concepts": [],
                "importance": "critical",
            }
        ]
        result = MemoryExtractor._parse_response(json.dumps(data))
        assert result[0].importance == "medium"

    def test_handles_json_embedded_in_text(self) -> None:
        inner = json.dumps(
            [
                {
                    "memory_type": "pattern",
                    "content": "Use factory pattern",
                    "related_files": [],
                    "concepts": ["pattern"],
                    "importance": "medium",
                }
            ]
        )
        text = f"Here are the memories:\n{inner}\nDone."
        result = MemoryExtractor._parse_response(text)
        assert len(result) == 1
        assert result[0].memory_type == "pattern"


class TestExtractFromTranscript:
    def test_returns_empty_for_empty_conversation(self) -> None:
        extractor = MemoryExtractor()
        # Empty conversation should return [] without calling the LLM
        result = extractor.extract_from_transcript("")
        assert result == []

    def test_returns_empty_for_whitespace_only(self) -> None:
        extractor = MemoryExtractor()
        result = extractor.extract_from_transcript("   \n  \n  ")
        assert result == []

    @patch("odk.core.extractor.MemoryExtractor._build_agent")
    def test_calls_agent_and_parses_response(self, mock_build_agent: MagicMock) -> None:
        mock_agent = MagicMock()
        llm_response = json.dumps(
            [
                {
                    "memory_type": "discovery",
                    "content": "JWT tokens expire after 1 hour by default in src/api/auth.py",
                    "related_files": ["src/api/auth.py"],
                    "concepts": ["how-it-works"],
                    "importance": "medium",
                },
                {
                    "memory_type": "gotcha",
                    "content": "Auth middleware must run before rate limiting in src/api/middleware.py",
                    "related_files": ["src/api/middleware.py"],
                    "concepts": ["gotcha", "how-it-works"],
                    "importance": "high",
                },
            ]
        )
        mock_agent.return_value = llm_response
        mock_build_agent.return_value = mock_agent

        extractor = MemoryExtractor()
        result = extractor.extract_from_transcript("[User]\nAdd JWT auth\n\n[Assistant]\nDone.")

        assert len(result) == 2
        assert result[0].memory_type == "discovery"
        assert "JWT" in result[0].content
        assert result[1].memory_type == "gotcha"
        assert result[1].importance == "high"

        # Verify the agent was called with a message containing the conversation
        call_args = mock_agent.call_args[0][0]
        assert "JWT auth" in call_args

    @patch("odk.core.extractor.MemoryExtractor._build_agent")
    def test_includes_task_context_in_message(self, mock_build_agent: MagicMock) -> None:
        mock_agent = MagicMock()
        mock_agent.return_value = "[]"
        mock_build_agent.return_value = mock_agent

        extractor = MemoryExtractor()
        extractor.extract_from_transcript("some convo", task_context="T-042: Add auth")

        call_args = mock_agent.call_args[0][0]
        assert "T-042" in call_args
        assert "some convo" in call_args


class TestExtractFromJsonl:
    @patch("odk.core.extractor.MemoryExtractor._build_agent")
    def test_parses_jsonl_then_extracts(self, mock_build_agent: MagicMock, tmp_path) -> None:
        # Write a minimal JSONL fixture
        jsonl = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"type": "user", "message": {"role": "user", "content": "Fix the bug"}}),
            json.dumps({"type": "assistant", "message": {"role": "assistant", "content": "Fixed it in handler.py"}}),
        ]
        jsonl.write_text("\n".join(lines))

        mock_agent = MagicMock()
        mock_agent.return_value = json.dumps(
            [
                {
                    "memory_type": "discovery",
                    "content": "Bug was in handler.py",
                    "related_files": ["handler.py"],
                    "concepts": ["problem-solution"],
                    "importance": "medium",
                }
            ]
        )
        mock_build_agent.return_value = mock_agent

        extractor = MemoryExtractor()
        result = extractor.extract_from_jsonl(jsonl)

        assert len(result) == 1
        assert result[0].content == "Bug was in handler.py"


class TestAbandonedExtraction:
    """Test that 'abandoned' is a valid extraction type."""

    def test_abandoned_in_valid_types(self) -> None:
        """The parser should accept 'abandoned' as a valid memory type."""
        data = [
            {
                "memory_type": "abandoned",
                "content": "Tried Redis for caching, rejected due to operational overhead",
                "related_files": ["src/cache.py"],
                "concepts": ["trade-off"],
                "importance": "high",
            }
        ]
        result = MemoryExtractor._parse_response(json.dumps(data))
        assert len(result) == 1
        assert result[0].memory_type == "abandoned"
        assert result[0].importance == "high"

    def test_extraction_prompt_includes_abandoned(self) -> None:
        """EXTRACTION_PROMPT must instruct the LLM to look for abandoned approaches."""
        from odk.core.extractor import EXTRACTION_PROMPT

        assert "abandoned" in EXTRACTION_PROMPT.lower()
        assert "rejected" in EXTRACTION_PROMPT.lower()


class TestStrandsImportError:
    def test_raises_clear_error_when_strands_missing(self) -> None:
        extractor = MemoryExtractor()
        with (
            patch.dict("sys.modules", {"strands": None, "strands.models.bedrock": None}),
            pytest.raises(ImportError, match="strands-agents"),
        ):
            extractor._build_agent()

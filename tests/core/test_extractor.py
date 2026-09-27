"""Tests for ydk.core.extractor — LLM-based memory extraction."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from ydk.core.extractor import ExtractedMemory, ExtractionResult, MemoryExtractor
from ydk.core.llm_provider import AnthropicLLMProvider


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


class FakeAnthropicClient:
    """Fake SDK client (system boundary): ``messages.parse`` validates canned data into ``output_format``."""

    def __init__(self, data: dict[str, object]) -> None:
        self._data = data
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def parse(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=kwargs["output_format"].model_validate(self._data))


def _extractor(memories: list[dict[str, object]]) -> tuple[MemoryExtractor, FakeAnthropicClient]:
    client = FakeAnthropicClient({"memories": memories})
    provider = AnthropicLLMProvider(client=client, model_id="claude-sonnet-5")
    return MemoryExtractor(llm_provider=provider), client


def _memory(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "memory_type": "discovery",
        "content": "AuthHandler uses HS256 algorithm",
        "related_files": ["src/api/auth.py"],
        "concepts": ["how-it-works"],
        "importance": "medium",
    }
    data.update(overrides)
    return data


class TestExtractionSchema:
    def test_rejects_unknown_memory_type(self) -> None:
        with pytest.raises(ValidationError):
            ExtractionResult.model_validate({"memories": [_memory(memory_type="bogus_type")]})

    def test_rejects_unknown_importance(self) -> None:
        with pytest.raises(ValidationError):
            ExtractionResult.model_validate({"memories": [_memory(importance="critical")]})


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

    def test_calls_provider_and_converts_structured_output(self) -> None:
        extractor, client = _extractor(
            [
                _memory(content="JWT tokens expire after 1 hour by default in src/api/auth.py"),
                _memory(
                    memory_type="gotcha",
                    content="Auth middleware must run before rate limiting in src/api/middleware.py",
                    related_files=["src/api/middleware.py"],
                    concepts=["gotcha", "how-it-works"],
                    importance="high",
                ),
            ]
        )
        result = extractor.extract_from_transcript("[User]\nAdd JWT auth\n\n[Assistant]\nDone.")

        assert len(result) == 2
        assert result[0] == ExtractedMemory(
            memory_type="discovery",
            content="JWT tokens expire after 1 hour by default in src/api/auth.py",
            related_files=["src/api/auth.py"],
            concepts=["how-it-works"],
            importance="medium",
        )
        assert result[1].memory_type == "gotcha"
        assert result[1].importance == "high"

        call = client.calls[-1]
        assert call["output_format"] is ExtractionResult
        assert "temperature" not in call
        assert "tool_choice" not in call
        assert "JWT auth" in call["messages"][0]["content"]

    def test_empty_memories(self) -> None:
        extractor, _ = _extractor([])
        assert extractor.extract_from_transcript("some convo") == []

    def test_skips_items_without_content(self) -> None:
        extractor, _ = _extractor([_memory(content="  "), _memory(content="Real content")])
        result = extractor.extract_from_transcript("some convo")
        assert [m.content for m in result] == ["Real content"]

    def test_accepts_abandoned_type(self) -> None:
        extractor, _ = _extractor([_memory(memory_type="abandoned", content="Tried Redis, rejected")])
        result = extractor.extract_from_transcript("some convo")
        assert result[0].memory_type == "abandoned"

    def test_includes_task_context_in_message(self) -> None:
        extractor, client = _extractor([])
        extractor.extract_from_transcript("some convo", task_context="T-042: Add auth")

        prompt = client.calls[-1]["messages"][0]["content"]
        assert "T-042" in prompt
        assert "some convo" in prompt


class TestExtractFromJsonl:
    def test_parses_jsonl_then_extracts(self, tmp_path) -> None:
        # Write a minimal JSONL fixture
        jsonl = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"type": "user", "message": {"role": "user", "content": "Fix the bug"}}),
            json.dumps({"type": "assistant", "message": {"role": "assistant", "content": "Fixed it in handler.py"}}),
        ]
        jsonl.write_text("\n".join(lines))

        extractor, _ = _extractor(
            [_memory(content="Bug was in handler.py", related_files=["handler.py"], concepts=["problem-solution"])]
        )
        result = extractor.extract_from_jsonl(jsonl)

        assert len(result) == 1
        assert result[0].content == "Bug was in handler.py"


class TestAbandonedExtraction:
    """Test that 'abandoned' is a valid extraction type."""

    def test_extraction_prompt_includes_abandoned(self) -> None:
        """EXTRACTION_PROMPT must instruct the LLM to look for abandoned approaches."""
        from ydk.core.extractor import EXTRACTION_PROMPT

        assert "abandoned" in EXTRACTION_PROMPT.lower()
        assert "rejected" in EXTRACTION_PROMPT.lower()


class TestNoProviderConfigured:
    def test_raises_clear_error_when_no_llm_provider_configured(self) -> None:
        extractor = MemoryExtractor()
        with (
            patch("ydk.core.llm_provider.get_llm_provider", return_value=None),
            pytest.raises(ImportError, match="LLM provider"),
        ):
            extractor._build_provider()


class TestBuildProviderMaxTokens:
    def test_builds_provider_with_large_max_tokens(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        with patch("anthropic.Anthropic", return_value=MagicMock()):
            provider = MemoryExtractor._build_provider()

        assert provider._max_tokens == 16000  # type: ignore[attr-defined]

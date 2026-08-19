"""Tests for the canonical LLMProvider abstraction and Anthropic-backed implementation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ydk.core.llm_provider import AnthropicLLMProvider, LLMProvider, get_llm_provider
from ydk.models.config import AIConfig

# ---------------------------------------------------------------------------
# AnthropicLLMProvider (mocks the anthropic SDK client — a system boundary)
# ---------------------------------------------------------------------------


class TestAnthropicLLMProvider:
    def test_invoke_builds_request_and_extracts_text(self) -> None:
        text_block = SimpleNamespace(type="text", text="hello world")
        client = MagicMock()
        client.messages.create.return_value = SimpleNamespace(content=[text_block])

        provider = AnthropicLLMProvider(client=client, model_id="claude-sonnet-5")
        result = provider.invoke("say hi")

        assert result == "hello world"
        client.messages.create.assert_called_once_with(
            model="claude-sonnet-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": "say hi"}],
        )

    def test_invoke_skips_non_text_blocks(self) -> None:
        thinking_block = SimpleNamespace(type="thinking", thinking="internal reasoning")
        text_block = SimpleNamespace(type="text", text="the answer")
        client = MagicMock()
        client.messages.create.return_value = SimpleNamespace(content=[thinking_block, text_block])

        provider = AnthropicLLMProvider(client=client, model_id="claude-sonnet-5")
        result = provider.invoke("prompt")

        assert result == "the answer"

    def test_invoke_returns_empty_string_when_no_text_block(self) -> None:
        thinking_block = SimpleNamespace(type="thinking", thinking="internal reasoning")
        client = MagicMock()
        client.messages.create.return_value = SimpleNamespace(content=[thinking_block])

        provider = AnthropicLLMProvider(client=client, model_id="claude-sonnet-5")
        result = provider.invoke("prompt")

        assert result == ""

    def test_conforms_to_llm_provider_protocol(self) -> None:
        client = MagicMock()
        provider = AnthropicLLMProvider(client=client, model_id="claude-sonnet-5")
        assert isinstance(provider, LLMProvider)


# ---------------------------------------------------------------------------
# get_llm_provider (fail-open factory)
# ---------------------------------------------------------------------------


class TestGetLlmProvider:
    def test_returns_anthropic_provider_for_anthropic_config(self) -> None:
        cfg = AIConfig(provider="anthropic", model_tiers={"fast": "claude-sonnet-5"})

        with patch("anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_anthropic_cls.return_value = mock_client

            provider = get_llm_provider(cfg)

        assert isinstance(provider, AnthropicLLMProvider)
        assert provider._client is mock_client
        assert provider._model_id == "claude-sonnet-5"

    def test_returns_none_for_unknown_provider(self) -> None:
        cfg = AIConfig(provider="does-not-exist", model_tiers={})

        assert get_llm_provider(cfg) is None

    def test_returns_none_on_exception(self) -> None:
        cfg = AIConfig(provider="anthropic", model_tiers={"fast": "claude-sonnet-5"})

        with patch("anthropic.Anthropic", side_effect=RuntimeError("boom")):
            assert get_llm_provider(cfg) is None

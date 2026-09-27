"""Tests for ydk.core.llm_provider — provider-agnostic LLM seam (no built-in provider)."""

from __future__ import annotations

import ydk.core.llm_provider as llm_provider_module
from ydk.core.llm_provider import LLMProvider


class _StubProvider:
    def invoke(self, prompt: str) -> str:
        return prompt


class TestLLMProviderProtocol:
    def test_stub_with_invoke_conforms(self) -> None:
        assert isinstance(_StubProvider(), LLMProvider)

    def test_object_without_invoke_does_not_conform(self) -> None:
        assert not isinstance(object(), LLMProvider)


class TestNoBuiltInProvider:
    """Issue #231: YDK makes no external LLM API calls, so no concrete provider ships."""

    def test_no_anthropic_provider(self) -> None:
        assert not hasattr(llm_provider_module, "AnthropicLLMProvider")

    def test_no_provider_factory(self) -> None:
        assert not hasattr(llm_provider_module, "get_llm_provider")

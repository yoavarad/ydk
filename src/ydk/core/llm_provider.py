"""Canonical LLM provider abstraction and Anthropic-backed implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ydk.models.config import AIConfig


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers used across YDK's core modules."""

    def invoke(self, prompt: str) -> str:
        """Send a prompt to an LLM and return the text response."""
        ...


class AnthropicLLMProvider:
    """LLMProvider implementation backed by the Anthropic SDK."""

    def __init__(self, client: object, model_id: str) -> None:
        self._client: Any = client
        self._model_id = model_id

    def invoke(self, prompt: str) -> str:
        """Send a prompt to Claude and return the first text block's content."""
        response = self._client.messages.create(
            model=self._model_id,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content:
            if block.type == "text":
                return block.text
        return ""


def _build_anthropic_provider(cfg: AIConfig) -> LLMProvider:
    import anthropic

    client = anthropic.Anthropic()
    model_id = cfg.model_tiers.get("fast", "claude-sonnet-5")
    return AnthropicLLMProvider(client=client, model_id=model_id)


_PROVIDER_BUILDERS = {
    "anthropic": _build_anthropic_provider,
}


def get_llm_provider(cfg: AIConfig) -> LLMProvider | None:
    """Construct an LLMProvider from an AIConfig, dispatching on ``cfg.provider``.

    Fails open: returns ``None`` on any error (missing import, missing
    config, unknown provider, etc.) instead of raising.
    """
    try:
        builder = _PROVIDER_BUILDERS.get(cfg.provider)
        if builder is None:
            return None
        return builder(cfg)
    except Exception:
        return None

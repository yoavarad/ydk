"""Canonical LLM provider abstraction and Anthropic-backed implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

if TYPE_CHECKING:
    from ydk.models.config import YdkConfig


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers used across YDK's core modules."""

    def invoke(self, prompt: str) -> str:
        """Send a prompt to an LLM and return the text response."""
        ...


class AnthropicLLMProvider:
    """LLMProvider implementation backed by the Anthropic SDK."""

    def __init__(self, client: object, model_id: str, max_tokens: int = 1024) -> None:
        self._client: Any = client
        self._model_id = model_id
        self._max_tokens = max_tokens

    def invoke(self, prompt: str) -> str:
        """Send a prompt to Claude and return the first text block's content.

        Raises ``ClaudeAPIError`` on API failures or truncated output.
        """
        from ydk.core.claude_client import create_message

        response = create_message(
            self._client,
            model=self._model_id,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content:
            if block.type == "text":
                return cast("Any", block).text
        return ""


def _build_anthropic_provider(cfg: YdkConfig, max_tokens: int) -> LLMProvider:
    from ydk.core.claude_client import build_client

    client = build_client(cfg.anthropic.api_key_env)
    model_id = cfg.ai.model_tiers.get("fast", "claude-sonnet-4-6")
    return AnthropicLLMProvider(client=client, model_id=model_id, max_tokens=max_tokens)


_PROVIDER_BUILDERS = {
    "anthropic": _build_anthropic_provider,
}


def get_llm_provider(cfg: YdkConfig, *, max_tokens: int = 1024) -> LLMProvider | None:
    """Construct an LLMProvider from a YdkConfig, dispatching on ``cfg.ai.provider``.

    Returns ``None`` for an unknown provider or an unexpected construction
    error. Missing credentials are not swallowed: ``MissingCredentialsError``
    propagates so callers can report it before any request is made.
    """
    from ydk.core.claude_client import ClaudeAPIError

    try:
        builder = _PROVIDER_BUILDERS.get(cfg.ai.provider)
        if builder is None:
            return None
        return builder(cfg, max_tokens)
    except ClaudeAPIError:
        raise
    except Exception:
        return None

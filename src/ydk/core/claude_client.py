"""Shared Claude (Anthropic) client factory and typed API error handling.

Every Claude call site builds its client through :func:`build_client` and
sends requests through :func:`create_message`, so credential resolution and
error reporting behave the same everywhere.
"""

from __future__ import annotations

import os
from typing import Any, cast

import anthropic

DEFAULT_API_KEY_ENV = "ANTHROPIC_API_KEY"

_SETUP_HINT = "see the `ydk init` setup instructions"


class ClaudeAPIError(Exception):
    """A Claude API failure with a user-facing message."""


class MissingCredentialsError(ClaudeAPIError):
    """No Anthropic credentials could be resolved."""


def build_client(
    api_key_env: str = DEFAULT_API_KEY_ENV,
    *,
    timeout: float | None = None,
    max_retries: int = anthropic.DEFAULT_MAX_RETRIES,
) -> anthropic.Anthropic:
    """Build an Anthropic client, failing fast when no credentials resolve.

    With the default ``api_key_env`` the SDK resolves credentials itself
    (``ANTHROPIC_API_KEY``, then ``ANTHROPIC_AUTH_TOKEN``, then a profile).
    A non-default env var name is read and passed explicitly.
    ``timeout=None`` keeps the SDK's default timeout.
    """
    client_kwargs: dict[str, Any] = {"max_retries": max_retries}
    if timeout is not None:
        client_kwargs["timeout"] = timeout
    if api_key_env != DEFAULT_API_KEY_ENV:
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise MissingCredentialsError(
                f"Claude API: invalid or missing API key -- {api_key_env} is not set ({_SETUP_HINT})."
            )
        return anthropic.Anthropic(api_key=api_key, **client_kwargs)

    client = anthropic.Anthropic(**client_kwargs)
    if client.api_key is None and client.auth_token is None and client.credentials is None:
        raise MissingCredentialsError(
            "Claude API: invalid or missing API key -- set ANTHROPIC_API_KEY "
            f"or ANTHROPIC_AUTH_TOKEN, or configure an Anthropic profile ({_SETUP_HINT})."
        )
    return client


def _translate(exc: anthropic.APIError, model: object) -> ClaudeAPIError:
    if isinstance(exc, anthropic.AuthenticationError):
        return ClaudeAPIError(f"Claude API: invalid or missing API key (401) -- {_SETUP_HINT}.")
    if isinstance(exc, anthropic.NotFoundError):
        return ClaudeAPIError(f"Claude API: not found (404) -- check the model id {model!r}.")
    if isinstance(exc, anthropic.RateLimitError):
        return ClaudeAPIError("Claude API: rate limit exceeded (429) -- retry later.")
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code >= 500:
            return ClaudeAPIError(f"Claude API: server error ({exc.status_code}) -- retry later.")
        return ClaudeAPIError(f"Claude API: request failed ({exc.status_code}): {exc.message}")
    if isinstance(exc, anthropic.APIConnectionError):
        return ClaudeAPIError(f"Claude API: could not connect to the API: {exc}")
    return ClaudeAPIError(f"Claude API: {type(exc).__name__}: {exc}")


def create_message(client: anthropic.Anthropic, **kwargs: object) -> anthropic.types.Message:
    """Call ``client.messages.create`` with typed error translation.

    Raises :class:`ClaudeAPIError` for any API failure and when the response
    was cut off by ``max_tokens`` (truncated output must not be parsed).
    """
    try:
        response = cast("Any", client).messages.create(**kwargs)
    except anthropic.APIError as exc:
        raise _translate(exc, kwargs.get("model")) from exc
    if getattr(response, "stop_reason", None) == "max_tokens":
        raise ClaudeAPIError(
            f"Claude API: response truncated (stop_reason=max_tokens, max_tokens={kwargs.get('max_tokens')})."
        )
    return cast("anthropic.types.Message", response)

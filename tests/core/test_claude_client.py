"""Tests for the shared Claude client factory and typed API error handling."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest
from pydantic import BaseModel

from ydk.core.claude_client import (
    ClaudeAPIError,
    MissingCredentialsError,
    build_client,
    create_message,
    parse_message,
    parse_response,
)

_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls: type[anthropic.APIStatusError], status: int) -> anthropic.APIStatusError:
    return cls("boom", response=httpx.Response(status, request=_REQUEST), body=None)


@pytest.fixture
def no_env_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_PROFILE",
        "ANTHROPIC_IDENTITY_TOKEN",
        "ANTHROPIC_IDENTITY_TOKEN_FILE",
        "ANTHROPIC_FEDERATION_RULE_ID",
        "ANTHROPIC_ORGANIZATION_ID",
    ):
        monkeypatch.delenv(var, raising=False)
    # System boundary: stop the SDK from discovering an on-disk profile.
    monkeypatch.setattr("anthropic._client.default_credentials", lambda **_: None)


class TestBuildClient:
    def test_default_env_uses_sdk_resolution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        client = build_client()
        assert client.api_key == "sk-test"

    def test_auth_token_is_accepted(self, no_env_credentials: None, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
        client = build_client()
        assert client.auth_token == "tok"

    def test_missing_credentials_raise_before_request(self, no_env_credentials: None) -> None:
        with pytest.raises(MissingCredentialsError, match="invalid or missing API key"):
            build_client()

    def test_custom_env_name_passes_key_explicitly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_CLAUDE_KEY", "sk-custom")
        client = build_client("MY_CLAUDE_KEY")
        assert client.api_key == "sk-custom"

    def test_custom_env_name_missing_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MY_CLAUDE_KEY", raising=False)
        with pytest.raises(MissingCredentialsError, match="MY_CLAUDE_KEY"):
            build_client("MY_CLAUDE_KEY")

    def test_client_kwargs_forwarded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        client = build_client(max_retries=5)
        assert client.max_retries == 5


class TestCreateMessage:
    def _client(self, *, side_effect: object = None, return_value: object = None) -> MagicMock:
        client = MagicMock()
        client.messages.create.side_effect = side_effect
        client.messages.create.return_value = return_value
        return client

    def test_returns_response(self) -> None:
        response = SimpleNamespace(stop_reason="end_turn", content=[])
        client = self._client(return_value=response)
        assert create_message(client, model="m", max_tokens=10, messages=[]) is response
        client.messages.create.assert_called_once_with(model="m", max_tokens=10, messages=[])

    def test_max_tokens_stop_reason_is_error(self) -> None:
        client = self._client(return_value=SimpleNamespace(stop_reason="max_tokens", content=[]))
        with pytest.raises(ClaudeAPIError, match="max_tokens"):
            create_message(client, model="m", max_tokens=10, messages=[])

    def test_authentication_error(self) -> None:
        client = self._client(side_effect=_status_error(anthropic.AuthenticationError, 401))
        with pytest.raises(ClaudeAPIError, match="invalid or missing API key"):
            create_message(client, model="m", max_tokens=10, messages=[])

    def test_not_found_error_mentions_model(self) -> None:
        client = self._client(side_effect=_status_error(anthropic.NotFoundError, 404))
        with pytest.raises(ClaudeAPIError, match="model"):
            create_message(client, model="bad-model", max_tokens=10, messages=[])

    def test_rate_limit_error(self) -> None:
        client = self._client(side_effect=_status_error(anthropic.RateLimitError, 429))
        with pytest.raises(ClaudeAPIError, match="rate limit"):
            create_message(client, model="m", max_tokens=10, messages=[])

    def test_server_error(self) -> None:
        client = self._client(side_effect=_status_error(anthropic.InternalServerError, 500))
        with pytest.raises(ClaudeAPIError, match="server error"):
            create_message(client, model="m", max_tokens=10, messages=[])

    def test_other_status_error(self) -> None:
        client = self._client(side_effect=_status_error(anthropic.BadRequestError, 400))
        with pytest.raises(ClaudeAPIError, match="400"):
            create_message(client, model="m", max_tokens=10, messages=[])

    def test_connection_error(self) -> None:
        client = self._client(side_effect=anthropic.APIConnectionError(request=_REQUEST))
        with pytest.raises(ClaudeAPIError, match="connect"):
            create_message(client, model="m", max_tokens=10, messages=[])

    def test_missing_credentials_is_claude_api_error(self) -> None:
        assert issubclass(MissingCredentialsError, ClaudeAPIError)


class _Verdict(BaseModel):
    ok: bool


class TestParseMessage:
    def _client(self, *, side_effect: object = None, return_value: object = None) -> MagicMock:
        client = MagicMock()
        client.messages.parse.side_effect = side_effect
        client.messages.parse.return_value = return_value
        return client

    def test_returns_parsed_output_and_passes_output_format(self) -> None:
        verdict = _Verdict(ok=True)
        client = self._client(return_value=SimpleNamespace(stop_reason="end_turn", parsed_output=verdict))
        result = parse_message(client, _Verdict, model="m", max_tokens=10, messages=[])
        assert result is verdict
        client.messages.parse.assert_called_once_with(model="m", max_tokens=10, messages=[], output_format=_Verdict)

    def test_max_tokens_stop_reason_is_error(self) -> None:
        client = self._client(return_value=SimpleNamespace(stop_reason="max_tokens", parsed_output=None))
        with pytest.raises(ClaudeAPIError, match="max_tokens"):
            parse_message(client, _Verdict, model="m", max_tokens=10, messages=[])

    def test_missing_parsed_output_is_error(self) -> None:
        client = self._client(return_value=SimpleNamespace(stop_reason="refusal", parsed_output=None))
        with pytest.raises(ClaudeAPIError, match="refusal"):
            parse_message(client, _Verdict, model="m", max_tokens=10, messages=[])

    def test_api_error_is_translated(self) -> None:
        client = self._client(side_effect=_status_error(anthropic.AuthenticationError, 401))
        with pytest.raises(ClaudeAPIError, match="invalid or missing API key"):
            parse_message(client, _Verdict, model="m", max_tokens=10, messages=[])

    def test_parse_response_returns_full_response(self) -> None:
        response = SimpleNamespace(stop_reason="end_turn", parsed_output=_Verdict(ok=False), usage=object())
        client = self._client(return_value=response)
        assert parse_response(client, _Verdict, model="m", max_tokens=10, messages=[]) is response

"""Tests for the canonical LLMProvider abstraction and Anthropic-backed implementation."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest
from pydantic import BaseModel

from ydk.core.claude_client import ClaudeAPIError, MissingCredentialsError
from ydk.core.llm_provider import (
    AnthropicLLMProvider,
    ClaudeCliError,
    ClaudeCliProvider,
    LLMProvider,
    LLMRequest,
    StructuredLLMProvider,
    SubagentHandoff,
    SubagentProvider,
    SubagentRequestPending,
    SubagentResponseError,
    get_llm_provider,
    tier_for_purpose,
)
from ydk.models.config import DEFAULT_MODEL_TIERS, AIConfig, AnthropicConfig, YdkConfig

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def _cfg(*, provider: str = "anthropic", model_tiers: dict[str, str] | None = None) -> YdkConfig:
    return YdkConfig(
        project={"name": "test"},
        ai=AIConfig(provider=provider, model_tiers=model_tiers or {"fast": "claude-sonnet-5"}),
        anthropic=AnthropicConfig(api_key_env="ANTHROPIC_API_KEY"),
    )


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

    def test_invoke_uses_configured_max_tokens(self) -> None:
        client = MagicMock()
        client.messages.create.return_value = SimpleNamespace(content=[], stop_reason="end_turn")

        AnthropicLLMProvider(client=client, model_id="m", max_tokens=16000).invoke("p")

        assert client.messages.create.call_args[1]["max_tokens"] == 16000

    def test_invoke_raises_on_truncated_response(self) -> None:
        client = MagicMock()
        client.messages.create.return_value = SimpleNamespace(content=[], stop_reason="max_tokens")

        with pytest.raises(ClaudeAPIError, match="max_tokens"):
            AnthropicLLMProvider(client=client, model_id="m").invoke("p")

    def test_invoke_translates_authentication_error(self) -> None:
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        client = MagicMock()
        client.messages.create.side_effect = anthropic.AuthenticationError(
            "bad key", response=httpx.Response(401, request=request), body=None
        )

        with pytest.raises(ClaudeAPIError, match="invalid or missing API key"):
            AnthropicLLMProvider(client=client, model_id="m").invoke("p")

    def test_conforms_to_llm_provider_protocol(self) -> None:
        client = MagicMock()
        provider = AnthropicLLMProvider(client=client, model_id="claude-sonnet-5")
        assert isinstance(provider, LLMProvider)


class _Answer(BaseModel):
    value: str


class TestAnthropicLLMProviderStructured:
    def test_invoke_structured_uses_parse_without_sampling_or_tool_choice(self) -> None:
        answer = _Answer(value="42")
        client = MagicMock()
        client.messages.parse.return_value = SimpleNamespace(stop_reason="end_turn", parsed_output=answer)

        provider = AnthropicLLMProvider(client=client, model_id="claude-sonnet-5", max_tokens=2048)
        result = provider.invoke_structured("question", _Answer)

        assert result is answer
        client.messages.parse.assert_called_once_with(
            model="claude-sonnet-5",
            max_tokens=2048,
            messages=[{"role": "user", "content": "question"}],
            output_format=_Answer,
        )

    def test_invoke_structured_raises_on_truncated_response(self) -> None:
        client = MagicMock()
        client.messages.parse.return_value = SimpleNamespace(stop_reason="max_tokens", parsed_output=None)

        with pytest.raises(ClaudeAPIError, match="max_tokens"):
            AnthropicLLMProvider(client=client, model_id="m").invoke_structured("p", _Answer)

    def test_satisfies_structured_protocol(self) -> None:
        assert isinstance(AnthropicLLMProvider(client=MagicMock(), model_id="m"), StructuredLLMProvider)


# ---------------------------------------------------------------------------
# get_llm_provider (fail-open factory)
# ---------------------------------------------------------------------------


class TestGetLlmProvider:
    def test_returns_anthropic_provider_for_anthropic_config(self) -> None:
        cfg = _cfg()

        with patch("anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_anthropic_cls.return_value = mock_client

            provider = get_llm_provider(cfg)

        assert isinstance(provider, AnthropicLLMProvider)
        assert provider._client is mock_client
        assert provider._model_id == "claude-sonnet-5"
        mock_anthropic_cls.assert_called_once()

    def test_uses_default_fast_tier_when_not_overridden(self) -> None:
        cfg = _cfg(model_tiers={"review": "claude-custom"})

        with patch("anthropic.Anthropic"):
            provider = get_llm_provider(cfg)

        assert isinstance(provider, AnthropicLLMProvider)
        assert provider._model_id == "claude-haiku-4-5"

    def test_returns_none_for_unknown_provider(self) -> None:
        cfg = _cfg(provider="does-not-exist", model_tiers={})

        assert get_llm_provider(cfg) is None

    def test_returns_none_on_exception(self) -> None:
        cfg = _cfg()

        with patch("anthropic.Anthropic", side_effect=RuntimeError("boom")):
            assert get_llm_provider(cfg) is None

    def test_max_tokens_forwarded(self) -> None:
        with patch("anthropic.Anthropic", return_value=MagicMock()):
            provider = get_llm_provider(_cfg(), max_tokens=16000)

        assert isinstance(provider, AnthropicLLMProvider)
        assert provider._max_tokens == 16000

    def test_missing_credentials_propagate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = YdkConfig(
            project={"name": "test"},
            ai=AIConfig(provider="anthropic", model_tiers={"fast": "m"}),
            anthropic=AnthropicConfig(api_key_env="YDK_TEST_MISSING_KEY"),
        )
        monkeypatch.delenv("YDK_TEST_MISSING_KEY", raising=False)

        with pytest.raises(MissingCredentialsError):
            get_llm_provider(cfg)


# ---------------------------------------------------------------------------
# LLMRequest
# ---------------------------------------------------------------------------


class _Other(BaseModel):
    count: int


def _request(
    *,
    purpose: str = "extract",
    system: str = "sys",
    user: str = "hello",
    output_schema: dict[str, object] | None = None,
    agent: str = "general-purpose",
    model: str = "claude-haiku-4-5",
    instructions: str = "",
) -> LLMRequest:
    return LLMRequest.build(
        purpose=purpose,
        system=system,
        user=user,
        output_schema=output_schema or _Answer.model_json_schema(),
        model_tier="fast",
        model=model,
        agent=agent,
        instructions=instructions,
    )


class TestLLMRequest:
    def test_id_stable_for_identical_input(self) -> None:
        assert _request().id == _request().id
        assert len(_request().id) == 64

    def test_id_changes_with_user_prompt(self) -> None:
        assert _request().id != _request(user="other").id

    def test_id_changes_with_system_prompt(self) -> None:
        assert _request().id != _request(system="other").id

    def test_id_changes_with_purpose(self) -> None:
        assert _request().id != _request(purpose="compaction").id

    def test_id_changes_with_schema(self) -> None:
        assert _request().id != _request(output_schema=_Other.model_json_schema()).id

    def test_id_ignores_routing_hints(self) -> None:
        assert _request().id == _request(agent="x", model="y", instructions="z").id


# ---------------------------------------------------------------------------
# SubagentProvider (real filesystem via tmp_path)
# ---------------------------------------------------------------------------


def _subagent(root: Path, *, collect: bool = False) -> SubagentProvider:
    return SubagentProvider(
        root,
        purpose="extract",
        model_tier="fast",
        model="claude-haiku-4-5",
        agent="general-purpose",
        instructions="be terse",
        collect=collect,
    )


def _request_id(prompt: str) -> str:
    return LLMRequest.compute_id(purpose="extract", system="", user=prompt, output_schema=_Answer.model_json_schema())


def _write_response(root: Path, prompt: str, body: str) -> Path:
    responses = root / "responses"
    responses.mkdir(parents=True, exist_ok=True)
    path = responses / f"{_request_id(prompt)}.json"
    path.write_text(body, encoding="utf-8")
    return path


class TestSubagentProvider:
    def test_missing_response_writes_request_and_raises_handoff(self, tmp_path: Path) -> None:
        with pytest.raises(SubagentHandoff) as exc:
            _subagent(tmp_path).invoke_structured("question", _Answer)

        path = tmp_path / "requests" / f"{_request_id('question')}.json"
        assert exc.value.request_paths == [path]
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["id"] == _request_id("question")
        assert data["user"] == "question"
        assert data["purpose"] == "extract"
        assert data["agent"] == "general-purpose"
        assert data["model"] == "claude-haiku-4-5"
        assert data["model_tier"] == "fast"
        assert data["instructions"] == "be terse"
        assert data["output_schema"] == _Answer.model_json_schema()

    def test_handoff_message_lists_paths(self, tmp_path: Path) -> None:
        with pytest.raises(SubagentHandoff, match=_request_id("question")):
            _subagent(tmp_path).invoke_structured("question", _Answer)

    def test_present_response_returns_validated_model(self, tmp_path: Path) -> None:
        _write_response(tmp_path, "question", '{"value": "42"}')

        result = _subagent(tmp_path).invoke_structured("question", _Answer)

        assert result == _Answer(value="42")
        assert not (tmp_path / "requests").exists()

    def test_invalid_response_raises_naming_file(self, tmp_path: Path) -> None:
        bad = _write_response(tmp_path, "question", '{"wrong": 1}')

        with pytest.raises(SubagentResponseError, match=bad.name):
            _subagent(tmp_path).invoke_structured("question", _Answer)

    def test_malformed_json_raises_naming_file(self, tmp_path: Path) -> None:
        bad = _write_response(tmp_path, "question", "not json")

        with pytest.raises(SubagentResponseError, match=bad.name):
            _subagent(tmp_path).invoke_structured("question", _Answer)

    def test_undecodable_response_raises_naming_file(self, tmp_path: Path) -> None:
        bad = _write_response(tmp_path, "question", "")
        bad.write_bytes(bytes([0xFF, 0xFE, 0x00]) + b"bad")

        with pytest.raises(SubagentResponseError, match=bad.name):
            _subagent(tmp_path).invoke_structured("question", _Answer)

    def test_handoff_escapes_fail_open_except_exception(self, tmp_path: Path) -> None:
        def fail_open_caller() -> str:
            try:
                return _subagent(tmp_path).invoke("q")
            except Exception:
                return "swallowed"

        with pytest.raises(SubagentHandoff):
            fail_open_caller()

    def test_invoke_returns_text_response(self, tmp_path: Path) -> None:
        provider = _subagent(tmp_path)
        with pytest.raises(SubagentHandoff) as exc:
            provider.invoke("say hi")
        request_path = exc.value.request_paths[0]
        responses = tmp_path / "responses"
        responses.mkdir()
        (responses / request_path.name).write_text('{"text": "hi"}', encoding="utf-8")

        assert provider.invoke("say hi") == "hi"

    def test_satisfies_structured_protocol(self, tmp_path: Path) -> None:
        assert isinstance(_subagent(tmp_path), StructuredLLMProvider)

    def test_collect_mode_batches_requests_into_one_handoff(self, tmp_path: Path) -> None:
        provider = _subagent(tmp_path, collect=True)
        for prompt in ("a", "b", "c", "a"):
            with pytest.raises(SubagentRequestPending):
                provider.invoke_structured(prompt, _Answer)

        expected = [tmp_path / "requests" / f"{_request_id(p)}.json" for p in ("a", "b", "c")]
        assert provider.pending() == expected

        with pytest.raises(SubagentHandoff) as exc:
            provider.flush()

        assert exc.value.request_paths == expected
        assert all(p.is_file() for p in expected)
        assert provider.pending() == []

    def test_flush_without_pending_is_noop(self, tmp_path: Path) -> None:
        _subagent(tmp_path, collect=True).flush()

    def test_collect_mode_returns_present_responses(self, tmp_path: Path) -> None:
        _write_response(tmp_path, "a", '{"value": "A"}')
        provider = _subagent(tmp_path, collect=True)

        assert provider.invoke_structured("a", _Answer) == _Answer(value="A")
        assert provider.pending() == []


# ---------------------------------------------------------------------------
# get_llm_provider routing
# ---------------------------------------------------------------------------


def _routed_cfg(tmp_path: Path, **ai: object) -> YdkConfig:
    data: dict[str, object] = {"subagent": {"dir": str(tmp_path / "llm")}}
    data.update(ai)
    return YdkConfig(project={"name": "test"}, ai=AIConfig.model_validate(data))


def _handoff_request(provider: StructuredLLMProvider | None) -> tuple[Path, dict[str, object]]:
    assert provider is not None
    with pytest.raises(SubagentHandoff) as exc:
        provider.invoke_structured("q", _Answer)
    path = exc.value.request_paths[0]
    return path, json.loads(path.read_text(encoding="utf-8"))


class TestGetLlmProviderRouting:
    def test_subagent_provider_selected(self, tmp_path: Path) -> None:
        provider = get_llm_provider(_routed_cfg(tmp_path, provider="subagent"), purpose="extract")
        assert isinstance(provider, SubagentProvider)

    def test_route_overrides_provider(self, tmp_path: Path) -> None:
        cfg = _routed_cfg(tmp_path, provider="anthropic", routes={"extract": "subagent"})
        assert isinstance(get_llm_provider(cfg, purpose="extract"), SubagentProvider)

    def test_unrouted_purpose_uses_global_provider(self, tmp_path: Path) -> None:
        cfg = _routed_cfg(tmp_path, provider="anthropic", routes={"extract": "subagent"})
        with patch("anthropic.Anthropic"):
            assert isinstance(get_llm_provider(cfg, purpose="compaction"), AnthropicLLMProvider)

    def test_anthropic_tier_follows_purpose(self) -> None:
        with patch("anthropic.Anthropic"):
            provider = get_llm_provider(_cfg(model_tiers={}), purpose="spec-review")
        assert isinstance(provider, AnthropicLLMProvider)
        assert provider._model_id == "claude-sonnet-5"

    def test_request_uses_purpose_agent_and_tier(self, tmp_path: Path) -> None:
        agents = {"ai-code-review": {"agent": "reviewer", "model": "opus", "instructions": "strict"}}
        cfg = _routed_cfg(tmp_path, provider="subagent", subagent={"dir": str(tmp_path / "llm"), "agents": agents})

        path, data = _handoff_request(get_llm_provider(cfg, purpose="ai-code-review"))

        assert path.parent == tmp_path / "llm" / "requests"
        assert (data["agent"], data["model"], data["instructions"]) == ("reviewer", "opus", "strict")
        assert data["model_tier"] == "review"
        assert data["purpose"] == "ai-code-review"

    def test_unknown_purpose_falls_back_to_default_agent(self, tmp_path: Path) -> None:
        agents = {"default": {"agent": "fallback"}}
        cfg = _routed_cfg(tmp_path, provider="subagent", subagent={"dir": str(tmp_path / "llm"), "agents": agents})

        _, data = _handoff_request(get_llm_provider(cfg, purpose="something-new"))

        assert data["agent"] == "fallback"
        assert data["model"] == "claude-haiku-4-5"
        assert data["model_tier"] == "fast"
        assert data["purpose"] == "something-new"

    def test_unknown_routed_provider_returns_none(self, tmp_path: Path) -> None:
        cfg = _routed_cfg(tmp_path, provider="subagent", routes={"extract": "nope"})
        assert get_llm_provider(cfg, purpose="extract") is None

    def test_default_agent_without_model_uses_purpose_tier_model(self, tmp_path: Path) -> None:
        agents = {"default": {"agent": "fallback"}}
        cfg = _routed_cfg(tmp_path, provider="subagent", subagent={"dir": str(tmp_path / "llm"), "agents": agents})

        _, data = _handoff_request(get_llm_provider(cfg, purpose="spec-review"))

        assert data["model"] == DEFAULT_MODEL_TIERS["review"]

    def test_no_purpose_uses_default_purpose(self, tmp_path: Path) -> None:
        _, data = _handoff_request(get_llm_provider(_routed_cfg(tmp_path, provider="subagent")))
        assert data["purpose"] == "default"


class TestTierForPurpose:
    @pytest.mark.parametrize(
        ("purpose", "tier"),
        [
            ("spec-review", "review"),
            ("ai-code-review", "review"),
            ("spec-alignment", "review"),
            ("retrospective", "review"),
            ("extract", "fast"),
            ("layer-b-scan", "fast"),
            ("complexity", "fast"),
            ("compaction", "fast"),
            ("contradiction", "fast"),
            ("checkpoint", "fast"),
            ("unknown", "fast"),
            (None, "fast"),
        ],
    )
    def test_mapping(self, purpose: str | None, tier: str) -> None:
        assert tier_for_purpose(purpose) == tier


class _CliAnswer(BaseModel):
    answer: str


def _completed(stdout: str, returncode: int = 0, stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


@pytest.fixture(autouse=True)
def _claude_on_path(request: pytest.FixtureRequest) -> Iterator[None]:
    if request.cls is not TestClaudeCliProvider:
        yield
        return
    with patch("ydk.core.llm_provider.shutil.which", side_effect=lambda b: f"/bin/{b}"):
        yield


class TestClaudeCliProvider:
    def test_structured_from_result_json(self) -> None:
        out = json.dumps({"type": "result", "result": json.dumps({"answer": "hi"})})
        with patch("ydk.core.llm_provider.subprocess.run", return_value=_completed(out)) as run:
            got = ClaudeCliProvider("claude-x").invoke_structured("p", _CliAnswer)
        assert got == _CliAnswer(answer="hi")
        cmd = run.call_args.args[0]
        assert cmd[:2] == ["/bin/claude", "-p"]
        assert "json" in cmd
        assert "--json-schema" in cmd
        assert "claude-x" in cmd
        assert run.call_args.kwargs["input"] == "p"

    def test_structured_prefers_structured_output(self) -> None:
        out = json.dumps({"result": "", "structured_output": {"answer": "so"}})
        with patch("ydk.core.llm_provider.subprocess.run", return_value=_completed(out)):
            assert ClaudeCliProvider().invoke_structured("p", _CliAnswer).answer == "so"

    def test_invoke_returns_text(self) -> None:
        out = json.dumps({"result": "plain text"})
        with patch("ydk.core.llm_provider.subprocess.run", return_value=_completed(out)) as run:
            assert ClaudeCliProvider().invoke("p") == "plain text"
        assert "--json-schema" not in run.call_args.args[0]

    def test_missing_binary_clear_error(self) -> None:
        with (
            patch("ydk.core.llm_provider.shutil.which", return_value=None),
            pytest.raises(ClaudeCliError, match=r"claude.* not found"),
        ):
            ClaudeCliProvider().invoke("p")

    def test_nonzero_exit_raises(self) -> None:
        with (
            patch("ydk.core.llm_provider.subprocess.run", return_value=_completed("", 1, "boom")),
            pytest.raises(ClaudeCliError, match="boom"),
        ):
            ClaudeCliProvider().invoke("p")

    def test_bad_json_raises(self) -> None:
        with (
            patch("ydk.core.llm_provider.subprocess.run", return_value=_completed("not json")),
            pytest.raises(ClaudeCliError),
        ):
            ClaudeCliProvider().invoke("p")

    def test_schema_mismatch_raises(self) -> None:
        out = json.dumps({"result": json.dumps({"wrong": 1})})
        with (
            patch("ydk.core.llm_provider.subprocess.run", return_value=_completed(out)),
            pytest.raises(ClaudeCliError),
        ):
            ClaudeCliProvider().invoke_structured("p", _CliAnswer)

    def test_get_llm_provider_claude_cli(self) -> None:
        cfg = _cfg(provider="claude-cli", model_tiers={"fast": "claude-fast"})
        provider = get_llm_provider(cfg, purpose="extract")
        assert isinstance(provider, ClaudeCliProvider)
        assert isinstance(provider, StructuredLLMProvider)


# ---------------------------------------------------------------------------
# System prompt + cacheable context (task 625)
# ---------------------------------------------------------------------------


class TestSystemAndCacheableContext:
    def test_anthropic_puts_context_in_cached_system_block(self) -> None:
        client = MagicMock()
        client.messages.parse.return_value = SimpleNamespace(stop_reason="end_turn", parsed_output=_Answer(value="x"))

        AnthropicLLMProvider(client=client, model_id="m").invoke_structured(
            "q", _Answer, system="be strict", cacheable_context="SPEC"
        )

        assert client.messages.parse.call_args.kwargs["system"] == [
            {"type": "text", "text": "be strict"},
            {"type": "text", "text": "SPEC", "cache_control": {"type": "ephemeral"}},
        ]

    def test_anthropic_system_only_has_no_cache_point(self) -> None:
        client = MagicMock()
        client.messages.parse.return_value = SimpleNamespace(stop_reason="end_turn", parsed_output=_Answer(value="x"))

        AnthropicLLMProvider(client=client, model_id="m").invoke_structured("q", _Answer, system="be strict")

        assert client.messages.parse.call_args.kwargs["system"] == [{"type": "text", "text": "be strict"}]

    def test_subagent_request_carries_system_and_context(self, tmp_path: Path) -> None:
        with pytest.raises(SubagentHandoff) as exc:
            _subagent(tmp_path).invoke_structured("q", _Answer, system="sys", cacheable_context="SPEC")

        data = json.loads(exc.value.request_paths[0].read_text(encoding="utf-8"))
        assert (data["system"], data["cacheable_context"], data["user"]) == ("sys", "SPEC", "q")

    def test_subagent_reads_response_for_context_request(self, tmp_path: Path) -> None:
        with pytest.raises(SubagentHandoff) as exc:
            _subagent(tmp_path).invoke_structured("q", _Answer, system="sys", cacheable_context="SPEC")
        request_id = exc.value.request_paths[0].stem
        (tmp_path / "responses").mkdir()
        (tmp_path / "responses" / f"{request_id}.json").write_text('{"value": "ok"}', encoding="utf-8")

        got = _subagent(tmp_path).invoke_structured("q", _Answer, system="sys", cacheable_context="SPEC")

        assert got.value == "ok"

    def test_id_changes_with_cacheable_context(self) -> None:
        base = {"purpose": "p", "system": "s", "user": "u", "output_schema": {}}
        assert LLMRequest.compute_id(**base, cacheable_context="A") != LLMRequest.compute_id(
            **base, cacheable_context="B"
        )

    def test_id_without_context_is_unchanged(self) -> None:
        base = {"purpose": "p", "system": "s", "user": "u", "output_schema": {}}
        legacy = hashlib.sha256(json.dumps(["p", "s", "u", {}], sort_keys=True).encode()).hexdigest()
        assert LLMRequest.compute_id(**base) == legacy

    def test_claude_cli_prepends_system_and_context(self) -> None:
        out = json.dumps({"structured_output": {"answer": "a"}})
        with (
            patch("ydk.core.llm_provider.shutil.which", return_value="/bin/claude"),
            patch("ydk.core.llm_provider.subprocess.run", return_value=_completed(out)) as run,
        ):
            ClaudeCliProvider().invoke_structured("q", _CliAnswer, system="sys", cacheable_context="SPEC")
        assert run.call_args.kwargs["input"] == "sys\n\nSPEC\n\nq"

    def test_get_llm_provider_tier_override(self) -> None:
        with patch("anthropic.Anthropic"):
            provider = get_llm_provider(_cfg(model_tiers={"fast": "f-model"}), purpose="spec-review", tier="fast")
        assert isinstance(provider, AnthropicLLMProvider)
        assert provider._model_id == "f-model"

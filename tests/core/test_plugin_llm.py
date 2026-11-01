"""Tests for ydk.core.plugin_llm -- LLM routing for AI verification plugins.

Mocks only at the Anthropic SDK boundary; the subagent provider is exercised
through real request/response files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from ydk.core.plugin_llm import LLM_HANDOFF_KEY, plugin_config, run_plugin_llm
from ydk.models.verification import NEEDS_LLM


class _Answer(BaseModel):
    verdict: str


@pytest.fixture(autouse=True)
def _clear_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)


def _context(tmp_path: Path, ai: dict[str, Any] | None = None, *, handoff: bool = False) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "project_root": str(tmp_path),
        "config": {"anthropic": {"api_key_env": "ANTHROPIC_API_KEY"}, "ai": ai or {}},
    }
    if handoff:
        ctx[LLM_HANDOFF_KEY] = True
    return ctx


def _run(ctx: dict[str, Any]) -> _Answer | dict[str, Any]:
    return run_plugin_llm(
        ctx,
        name="demo",
        purpose="ai-code-review",
        prompt="Is it good?",
        output_format=_Answer,
        kind="answer",
        start=0.0,
    )


class TestPluginConfig:
    def test_relative_subagent_dir_resolves_against_project_root(self, tmp_path: Path) -> None:
        cfg = plugin_config(_context(tmp_path, {"provider": "subagent"}))

        assert Path(cfg.ai.subagent.dir) == tmp_path / ".ydk" / "llm"
        assert cfg.ai.provider == "subagent"

    def test_absolute_subagent_dir_is_kept(self, tmp_path: Path) -> None:
        elsewhere = tmp_path / "elsewhere"
        cfg = plugin_config(_context(tmp_path / "proj", {"subagent": {"dir": str(elsewhere)}}))

        assert Path(cfg.ai.subagent.dir) == elsewhere

    def test_missing_config_uses_defaults(self, tmp_path: Path) -> None:
        cfg = plugin_config({"project_root": str(tmp_path)})

        assert cfg.ai.provider == "anthropic"
        assert cfg.anthropic.api_key_env == "ANTHROPIC_API_KEY"


class TestSubagentMode:
    def test_outside_task_done_reports_skipped(self, tmp_path: Path) -> None:
        result = _run(_context(tmp_path, {"provider": "subagent"}))

        assert isinstance(result, dict)
        assert result["passed"] is True
        assert result["detail"]["status"] == "SKIPPED"
        assert "ydk task done" in result["detail"]["skip_reason"]
        assert not (tmp_path / ".ydk" / "llm").exists()

    def test_route_override_to_subagent_also_skips(self, tmp_path: Path) -> None:
        result = _run(_context(tmp_path, {"provider": "anthropic", "routes": {"ai-code-review": "subagent"}}))

        assert isinstance(result, dict)
        assert result["detail"]["status"] == "SKIPPED"

    def test_inside_task_done_returns_needs_llm_with_request_paths(self, tmp_path: Path) -> None:
        result = _run(_context(tmp_path, {"provider": "subagent"}, handoff=True))

        assert isinstance(result, dict)
        assert result["passed"] is False
        assert result["detail"]["status"] == NEEDS_LLM
        assert result["detail"]["no_cache"] is True
        [path] = result["detail"]["request_paths"]
        request = json.loads(Path(path).read_text(encoding="utf-8"))
        assert request["purpose"] == "ai-code-review"
        assert request["user"] == "Is it good?"
        assert Path(path).parent == tmp_path / ".ydk" / "llm" / "requests"

    def test_rerun_consumes_response(self, tmp_path: Path) -> None:
        first = _run(_context(tmp_path, {"provider": "subagent"}, handoff=True))
        assert isinstance(first, dict)
        request_path = Path(first["detail"]["request_paths"][0])
        response_path = tmp_path / ".ydk" / "llm" / "responses" / request_path.name
        response_path.parent.mkdir(parents=True)
        response_path.write_text(json.dumps({"verdict": "ship it"}), encoding="utf-8")

        second = _run(_context(tmp_path, {"provider": "subagent"}, handoff=True))

        assert second == _Answer(verdict="ship it")

    def test_invalid_response_fails_without_cache(self, tmp_path: Path) -> None:
        first = _run(_context(tmp_path, {"provider": "subagent"}, handoff=True))
        assert isinstance(first, dict)
        name = Path(first["detail"]["request_paths"][0]).name
        response_path = tmp_path / ".ydk" / "llm" / "responses" / name
        response_path.parent.mkdir(parents=True)
        response_path.write_text("{}", encoding="utf-8")

        second = _run(_context(tmp_path, {"provider": "subagent"}, handoff=True))

        assert isinstance(second, dict)
        assert second["passed"] is False
        assert second["detail"]["error"] is True
        assert second["detail"]["no_cache"] is True
        assert str(response_path) in second["output"]


class TestAnthropicRoute:
    def test_returns_parsed_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        client = MagicMock()
        client.messages.parse.return_value = MagicMock(parsed_output=_Answer(verdict="ok"), stop_reason="end_turn")

        with patch("anthropic.Anthropic", return_value=client):
            result = _run(_context(tmp_path, {"model_tiers": {"review": "claude-review-x"}}))

        assert result == _Answer(verdict="ok")
        kwargs = client.messages.parse.call_args.kwargs
        assert kwargs["model"] == "claude-review-x"
        assert kwargs["output_format"] is _Answer
        assert kwargs["max_tokens"] == 8192
        assert kwargs["messages"] == [{"role": "user", "content": "Is it good?"}]

    def test_missing_credentials_fail_with_setup_guidance(self, tmp_path: Path) -> None:
        result = _run(_context(tmp_path))

        assert isinstance(result, dict)
        assert result["passed"] is False
        assert "ydk init" in result["output"]
        assert result["detail"]["credential_error"] is True
        assert result["detail"]["no_cache"] is True

    def test_unknown_provider_fails(self, tmp_path: Path) -> None:
        result = _run(_context(tmp_path, {"provider": "nope"}))

        assert isinstance(result, dict)
        assert result["passed"] is False
        assert "nope" in result["output"]
        assert result["detail"]["no_cache"] is True

    def test_schema_mismatch_reports_malformed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        client = MagicMock()
        client.messages.parse.side_effect = lambda **kw: kw["output_format"].model_validate({"verdict": 3})

        with patch("anthropic.Anthropic", return_value=client):
            result = _run(_context(tmp_path))

        assert isinstance(result, dict)
        assert result["passed"] is False
        assert "malformed answer from model" in result["output"]
        assert result["detail"]["malformed"] is True

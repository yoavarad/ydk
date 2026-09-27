"""Tests for AI verification plugins (spec-alignment, ai-code-review).

Mocks only at the Anthropic SDK boundary (``anthropic.Anthropic``), per the
project's no-mocks-of-internal-classes rule.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest

if TYPE_CHECKING:
    import types

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SPEC_ALIGNMENT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "verifications" / "spec-alignment" / "check.py"
)
AI_CODE_REVIEW_PATH = (
    Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "verifications" / "ai-code-review" / "check.py"
)


def _load_check_module(path: Path, name: str) -> types.ModuleType:
    """Import a check.py as a module for direct testing."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_context(
    tmp_path: Path,
    changed_files: list[str] | None = None,
    spec_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Build a standard verification context dict."""
    return {
        "project_root": str(tmp_path),
        "changed_files": changed_files or [],
        "spec_refs": spec_refs or [],
        "config": {
            "anthropic": {"api_key_env": "ANTHROPIC_API_KEY"},
            "spec_check": {
                "model": "claude-sonnet-4-6",
                "thresholds": {"architecture": 8},
            },
        },
    }


def _write_file(root: Path, relpath: str, content: str) -> None:
    """Write a file at root/relpath."""
    full = root / relpath
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)


def _mock_tool_use_response(tool_input: dict[str, Any]) -> MagicMock:
    """Build a fake anthropic.types.Message with a single tool_use block."""
    block = MagicMock()
    block.type = "tool_use"
    block.input = tool_input
    message = MagicMock()
    message.content = [block]
    message.stop_reason = "tool_use"
    return message


@pytest.fixture(autouse=True)
def _clear_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)


# ---------------------------------------------------------------------------
# Spec-alignment tests
# ---------------------------------------------------------------------------


class TestSpecAlignmentSkips:
    """Test graceful skip conditions for spec-alignment."""

    def test_skip_when_no_changed_files(self, tmp_path: Path) -> None:
        mod = _load_check_module(SPEC_ALIGNMENT_PATH, "spec_alignment_check")
        ctx = _make_context(tmp_path, changed_files=[], spec_refs=["docs/spec.md"])

        result = mod.run_check(ctx)

        assert result["passed"] is True
        assert "No changed files" in result["output"]

    def test_skip_when_no_spec_refs(self, tmp_path: Path) -> None:
        mod = _load_check_module(SPEC_ALIGNMENT_PATH, "spec_alignment_check")
        ctx = _make_context(tmp_path, changed_files=["src/main.py"], spec_refs=[])
        _write_file(tmp_path, "src/main.py", "print('hello')")

        result = mod.run_check(ctx)

        assert result["passed"] is True
        assert "No spec references" in result["output"]


class TestSpecAlignmentMissingCredentials:
    """Missing credentials must fail loudly, not skip silently."""

    def test_missing_key_fails_with_setup_guidance(self, tmp_path: Path) -> None:
        mod = _load_check_module(SPEC_ALIGNMENT_PATH, "spec_alignment_check")
        ctx = _make_context(tmp_path, changed_files=["src/main.py"], spec_refs=["docs/spec.md"])
        _write_file(tmp_path, "src/main.py", "print('hello')")
        _write_file(tmp_path, "docs/spec.md", "# Spec")

        result = mod.run_check(ctx)

        assert result["passed"] is False
        assert "ydk init" in result["output"]
        assert result["detail"]["credential_error"] is True
        assert result["detail"]["no_cache"] is True


class TestSpecAlignmentWithMockedClient:
    """Test spec-alignment calling the anthropic SDK directly (mocked at the SDK boundary)."""

    def test_passing_evaluation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module(SPEC_ALIGNMENT_PATH, "spec_alignment_check")
        _write_file(tmp_path, "src/main.py", "def greet(name: str) -> str:\n    return f'Hello {name}'")
        _write_file(tmp_path, "docs/spec.md", "# Greeting API\nMust accept name parameter.")

        ctx = _make_context(tmp_path, changed_files=["src/main.py"], spec_refs=["docs/spec.md"])
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        evaluation = {
            "dimensions": {
                "entity_accuracy": {"score": 9, "reasoning": "Entities match spec."},
                "interface_compliance": {"score": 9, "reasoning": "Interface matches."},
                "error_handling": {"score": 8, "reasoning": "Basic handling present."},
                "boundary_respect": {"score": 9, "reasoning": "Boundaries respected."},
                "scope_compliance": {"score": 9, "reasoning": "Within scope."},
                "cross_cutting_adherence": {"score": 8, "reasoning": "Logging adequate."},
            },
            "overall_score": 9,
            "summary": "Code aligns well with spec.",
        }

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_tool_use_response(evaluation)

        with patch("anthropic.Anthropic", return_value=mock_client):
            result = mod.run_check(ctx)

        assert result["passed"] is True
        assert result["detail"]["overall_score"] == 9
        assert "9/10" in result["output"]
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        assert call_kwargs["tool_choice"] == {"type": "tool", "name": "submit_evaluation"}

    def test_failing_evaluation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module(SPEC_ALIGNMENT_PATH, "spec_alignment_check")
        _write_file(tmp_path, "src/main.py", "x = 1")
        _write_file(tmp_path, "docs/spec.md", "# Complex API spec")

        ctx = _make_context(tmp_path, changed_files=["src/main.py"], spec_refs=["docs/spec.md"])
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        evaluation = {
            "dimensions": {
                "entity_accuracy": {"score": 3, "reasoning": "Missing entities."},
                "interface_compliance": {"score": 2, "reasoning": "No interface."},
                "error_handling": {"score": 1, "reasoning": "No error handling."},
                "boundary_respect": {"score": 4, "reasoning": "No boundaries."},
                "scope_compliance": {"score": 3, "reasoning": "Out of scope."},
                "cross_cutting_adherence": {"score": 2, "reasoning": "Missing."},
            },
            "overall_score": 3,
            "summary": "Code does not align with spec.",
        }

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_tool_use_response(evaluation)

        with patch("anthropic.Anthropic", return_value=mock_client):
            result = mod.run_check(ctx)

        assert result["passed"] is False
        assert result["detail"]["overall_score"] == 3

    def test_authentication_error_fails_loudly_and_is_not_cached(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mod = _load_check_module(SPEC_ALIGNMENT_PATH, "spec_alignment_check")
        _write_file(tmp_path, "src/main.py", "x = 1")
        _write_file(tmp_path, "docs/spec.md", "# Spec")

        ctx = _make_context(tmp_path, changed_files=["src/main.py"], spec_refs=["docs/spec.md"])
        monkeypatch.setenv("ANTHROPIC_API_KEY", "bad-key")

        fake_response = httpx.Response(401, request=httpx.Request("POST", "https://api.anthropic.com"))
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.AuthenticationError(
            "invalid x-api-key", response=fake_response, body=None
        )

        with patch("anthropic.Anthropic", return_value=mock_client):
            result = mod.run_check(ctx)

        assert result["passed"] is False
        assert "401" in result["output"]
        assert result["detail"]["no_cache"] is True


# ---------------------------------------------------------------------------
# AI code review tests
# ---------------------------------------------------------------------------


class TestAiCodeReviewSkips:
    """Test graceful skip conditions for ai-code-review."""

    def test_skip_when_no_changed_files(self, tmp_path: Path) -> None:
        mod = _load_check_module(AI_CODE_REVIEW_PATH, "ai_code_review_check")
        ctx = _make_context(tmp_path, changed_files=[])

        result = mod.run_check(ctx)

        assert result["passed"] is True
        assert "No changed files" in result["output"]


class TestAiCodeReviewMissingCredentials:
    """Missing credentials must fail loudly, not skip silently."""

    def test_missing_key_fails_with_setup_guidance(self, tmp_path: Path) -> None:
        mod = _load_check_module(AI_CODE_REVIEW_PATH, "ai_code_review_check")
        ctx = _make_context(tmp_path, changed_files=["src/main.py"])
        _write_file(tmp_path, "src/main.py", "print('hello')")

        result = mod.run_check(ctx)

        assert result["passed"] is False
        assert "ydk init" in result["output"]
        assert result["detail"]["credential_error"] is True
        assert result["detail"]["no_cache"] is True


class TestAiCodeReviewWithMockedClient:
    """Test ai-code-review calling the anthropic SDK directly (mocked at the SDK boundary)."""

    def test_clean_review_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module(AI_CODE_REVIEW_PATH, "ai_code_review_check")
        _write_file(tmp_path, "src/main.py", "def safe_func() -> str:\n    return 'ok'")

        ctx = _make_context(tmp_path, changed_files=["src/main.py"])
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        review = {"findings": [], "summary": "No issues found.", "passed": True}
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_tool_use_response(review)

        with patch("anthropic.Anthropic", return_value=mock_client):
            result = mod.run_check(ctx)

        assert result["passed"] is True
        assert result["detail"]["critical_count"] == 0
        assert "No issues found" in result["output"]

    def test_critical_finding_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module(AI_CODE_REVIEW_PATH, "ai_code_review_check")
        _write_file(tmp_path, "src/main.py", "password = 'hunter2'")

        ctx = _make_context(tmp_path, changed_files=["src/main.py"])
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        review = {
            "findings": [
                {
                    "severity": "critical",
                    "category": "security",
                    "file": "src/main.py",
                    "description": "Hardcoded password found",
                    "suggestion": "Use environment variables or secrets manager",
                }
            ],
            "summary": "Critical security issue found.",
            "passed": False,
        }
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_tool_use_response(review)

        with patch("anthropic.Anthropic", return_value=mock_client):
            result = mod.run_check(ctx)

        assert result["passed"] is False
        assert result["detail"]["critical_count"] == 1
        assert "CRITICAL" in result["output"]
        assert "Hardcoded password" in result["output"]

    def test_warning_only_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module(AI_CODE_REVIEW_PATH, "ai_code_review_check")
        _write_file(tmp_path, "src/main.py", "x = 1  # short var name")

        ctx = _make_context(tmp_path, changed_files=["src/main.py"])
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        review = {
            "findings": [
                {
                    "severity": "warning",
                    "category": "best_practices",
                    "file": "src/main.py",
                    "description": "Variable name too short",
                    "suggestion": "Use descriptive name",
                }
            ],
            "summary": "Minor quality issue.",
            "passed": True,
        }
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_tool_use_response(review)

        with patch("anthropic.Anthropic", return_value=mock_client):
            result = mod.run_check(ctx)

        assert result["passed"] is True
        assert result["detail"]["warning_count"] == 1
        assert result["detail"]["critical_count"] == 0

    def test_rate_limit_error_fails_loudly_and_is_not_cached(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mod = _load_check_module(AI_CODE_REVIEW_PATH, "ai_code_review_check")
        _write_file(tmp_path, "src/main.py", "x = 1")

        ctx = _make_context(tmp_path, changed_files=["src/main.py"])
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        fake_response = httpx.Response(429, request=httpx.Request("POST", "https://api.anthropic.com"))
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.RateLimitError(
            "rate limited", response=fake_response, body=None
        )

        with patch("anthropic.Anthropic", return_value=mock_client):
            result = mod.run_check(ctx)

        assert result["passed"] is False
        assert "429" in result["output"] or "rate limit" in result["output"].lower()
        assert result["detail"]["no_cache"] is True


class TestPluginCrashReportsFailure:
    """A crash inside run_check must never report PASS."""

    @pytest.mark.parametrize(
        ("path", "name"),
        [
            (AI_CODE_REVIEW_PATH, "ai-code-review"),
            (SPEC_ALIGNMENT_PATH, "spec-alignment"),
        ],
    )
    def test_crash_in_run_check_fails(
        self, path: Path, name: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import io
        import sys

        mod = _load_check_module(path, name.replace("-", "_") + "_crash")

        def boom(_ctx: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("agent exploded")

        monkeypatch.setattr(mod, "run_check", boom)
        monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

        with pytest.raises(SystemExit) as exc_info:
            mod.main()

        assert exc_info.value.code == 1
        result = json.loads(capsys.readouterr().out)
        assert result["passed"] is False
        assert not result["output"].startswith("SKIPPED")
        assert result["output"].startswith("ERROR: plugin error")
        assert result["detail"]["crashed"] is True
        assert result["detail"]["no_cache"] is True
        assert "agent exploded" in result["detail"]["error"]

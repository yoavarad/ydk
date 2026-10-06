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
            "ai": {"model_tiers": {"review": "claude-review-override"}},
            "spec_check": {
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
        assert call_kwargs["model"] == "claude-review-override"
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
        assert mock_client.messages.create.call_args.kwargs["model"] == "claude-review-override"

    def test_defaults_to_review_tier_when_context_has_no_ai_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ydk.models.config import DEFAULT_MODEL_TIERS

        mod = _load_check_module(AI_CODE_REVIEW_PATH, "ai_code_review_check")
        _write_file(tmp_path, "src/main.py", "x = 1")

        ctx = _make_context(tmp_path, changed_files=["src/main.py"])
        del ctx["config"]["ai"]
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        review = {"findings": [], "summary": "No issues found.", "passed": True}
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_tool_use_response(review)

        with patch("anthropic.Anthropic", return_value=mock_client):
            mod.run_check(ctx)

        assert mock_client.messages.create.call_args.kwargs["model"] == DEFAULT_MODEL_TIERS["review"]

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


# ---------------------------------------------------------------------------
# Task-scope grading (both plugins)
# ---------------------------------------------------------------------------

_TASK_SCOPE = {
    "title": "Add greeting endpoint",
    "description": "Implement only the greet() function; logging is owned by a sibling task.",
    "acceptance_criteria": ["greet() returns 'Hello <name>'", "greet() rejects empty names"],
}

_PASSING_EVALUATION = {
    "dimensions": {
        dim: {"score": 9, "reasoning": "ok"}
        for dim in (
            "entity_accuracy",
            "interface_compliance",
            "error_handling",
            "boundary_respect",
            "scope_compliance",
            "cross_cutting_adherence",
        )
    },
    "overall_score": 9,
    "summary": "Task-owned requirements satisfied.",
}

_CLEAN_REVIEW = {"findings": [], "summary": "No issues found.", "passed": True}


@pytest.mark.parametrize(
    ("path", "module_name", "tool_response"),
    [
        (SPEC_ALIGNMENT_PATH, "spec_alignment_scope", _PASSING_EVALUATION),
        (AI_CODE_REVIEW_PATH, "ai_code_review_scope", _CLEAN_REVIEW),
    ],
)
class TestTaskScopeGrading:
    """Plugins grade against the task's scope, not the whole spec, when task_scope is given."""

    def _run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        path: Path,
        module_name: str,
        tool_response: dict[str, Any],
        task_scope: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], str]:
        mod = _load_check_module(path, module_name)
        _write_file(tmp_path, "src/main.py", "def greet(name: str) -> str:\n    return f'Hello {name}'")
        _write_file(tmp_path, "docs/spec.md", "# Greeting API\nMust accept name.\nMust log every call.")
        ctx = _make_context(tmp_path, changed_files=["src/main.py"], spec_refs=["docs/spec.md"])
        if task_scope is not None:
            ctx["task_scope"] = task_scope
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_tool_use_response(tool_response)
        with patch("anthropic.Anthropic", return_value=mock_client):
            result = mod.run_check(ctx)

        user_message = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
        return result, user_message

    def test_prompt_contains_task_scope_and_out_of_scope_instruction(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        path: Path,
        module_name: str,
        tool_response: dict[str, Any],
    ) -> None:
        result, user_message = self._run(tmp_path, monkeypatch, path, module_name, tool_response, _TASK_SCOPE)

        assert result["passed"] is True
        assert "=== TASK SCOPE ===" in user_message
        assert _TASK_SCOPE["title"] in user_message
        assert _TASK_SCOPE["description"] in user_message
        for criterion in _TASK_SCOPE["acceptance_criteria"]:
            assert criterion in user_message
        lowered = user_message.lower()
        assert "not applicable" in lowered
        assert "only" in lowered
        assert "owned by this task" in lowered

    def test_without_task_scope_prompt_is_unchanged(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        path: Path,
        module_name: str,
        tool_response: dict[str, Any],
    ) -> None:
        _, user_message = self._run(tmp_path, monkeypatch, path, module_name, tool_response, None)

        assert "TASK SCOPE" not in user_message
        assert "not applicable" not in user_message.lower()


# ---------------------------------------------------------------------------
# Malformed tool output (task 297)
# ---------------------------------------------------------------------------

_GOOD_DIMS = {
    d: {"score": 9, "reasoning": "ok"}
    for d in (
        "entity_accuracy",
        "interface_compliance",
        "error_handling",
        "boundary_respect",
        "scope_compliance",
        "cross_cutting_adherence",
    )
}


def _run_with_tool_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: Path, name: str, tool_input: Any, with_spec: bool
) -> dict[str, Any]:
    mod = _load_check_module(path, name)
    _write_file(tmp_path, "src/main.py", "x = 1")
    _write_file(tmp_path, "docs/spec.md", "# Spec")
    ctx = _make_context(tmp_path, changed_files=["src/main.py"], spec_refs=["docs/spec.md"] if with_spec else [])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_tool_use_response(tool_input)
    with patch("anthropic.Anthropic", return_value=mock_client):
        return mod.run_check(ctx)


class TestMalformedSpecAlignmentOutput:
    @pytest.mark.parametrize(
        "tool_input",
        [
            "not a dict",
            {"dimensions": "all good", "overall_score": 9, "summary": "s"},
            {"dimensions": {**_GOOD_DIMS, "entity_accuracy": "9/10 fine"}, "overall_score": 9, "summary": "s"},
            {"dimensions": _GOOD_DIMS, "overall_score": "high", "summary": "s"},
        ],
    )
    def test_malformed_evaluation_fails_cleanly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool_input: Any
    ) -> None:
        result = _run_with_tool_input(
            tmp_path, monkeypatch, SPEC_ALIGNMENT_PATH, "spec_alignment_check", tool_input, True
        )
        assert result["passed"] is False
        assert "malformed evaluation from model" in result["output"]
        assert "plugin error" not in result["output"]
        assert result["detail"]["no_cache"] is True
        assert not result["detail"].get("crashed")


class TestMalformedAiCodeReviewOutput:
    @pytest.mark.parametrize(
        "tool_input",
        [
            "not a dict",
            {"findings": "none", "summary": "s"},
            {"findings": ["looks bad"], "summary": "s"},
        ],
    )
    def test_malformed_review_fails_cleanly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool_input: Any
    ) -> None:
        result = _run_with_tool_input(
            tmp_path, monkeypatch, AI_CODE_REVIEW_PATH, "ai_code_review_check", tool_input, False
        )
        assert result["passed"] is False
        assert "malformed review from model" in result["output"]
        assert "plugin error" not in result["output"]
        assert result["detail"]["no_cache"] is True
        assert not result["detail"].get("crashed")

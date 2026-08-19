"""Tests for AI verification plugins (spec-alignment, ai-code-review)."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    import pytest

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


# ---------------------------------------------------------------------------
# Spec-alignment tests
# ---------------------------------------------------------------------------


class TestSpecAlignmentSkips:
    """Test graceful skip conditions for spec-alignment."""

    def test_skip_when_strands_not_installed(self, tmp_path: Path) -> None:
        mod = _load_check_module(SPEC_ALIGNMENT_PATH, "spec_alignment_check")
        ctx = _make_context(tmp_path, changed_files=["src/main.py"])

        # Simulate strands not importable
        with patch.dict(sys.modules, {"strands": None, "strands.models.anthropic": None}):
            # Reload won't help since the import is inside the function,
            # so we patch the import mechanism
            original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

            def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
                if name in ("strands", "strands.models.anthropic"):
                    raise ImportError(f"No module named '{name}'")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = mod.run_check(ctx)

        assert result["passed"] is True
        assert "SKIPPED" in result["output"]
        assert "strands-agents not installed" in result["output"]
        assert result["detail"]["skipped"] is True

    def test_skip_when_api_key_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module(SPEC_ALIGNMENT_PATH, "spec_alignment_check")
        ctx = _make_context(tmp_path, changed_files=["src/main.py"], spec_refs=["docs/spec.md"])
        _write_file(tmp_path, "src/main.py", "print('hello')")
        _write_file(tmp_path, "docs/spec.md", "# Spec")

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        mock_strands = MagicMock()
        mock_anthropic_model = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "strands": mock_strands,
                "strands.models": MagicMock(),
                "strands.models.anthropic": mock_anthropic_model,
            },
        ):
            result = mod.run_check(ctx)

        assert result["passed"] is True
        assert "SKIPPED" in result["output"]
        assert "ANTHROPIC_API_KEY not configured" in result["output"]

    def test_skip_when_no_changed_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module(SPEC_ALIGNMENT_PATH, "spec_alignment_check")
        ctx = _make_context(tmp_path, changed_files=[], spec_refs=["docs/spec.md"])

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        mock_strands = MagicMock()
        mock_anthropic_model = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "strands": mock_strands,
                "strands.models": MagicMock(),
                "strands.models.anthropic": mock_anthropic_model,
            },
        ):
            result = mod.run_check(ctx)

        assert result["passed"] is True
        assert "No changed files" in result["output"]

    def test_skip_when_no_spec_refs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module(SPEC_ALIGNMENT_PATH, "spec_alignment_check")
        ctx = _make_context(tmp_path, changed_files=["src/main.py"], spec_refs=[])
        _write_file(tmp_path, "src/main.py", "print('hello')")

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        mock_strands = MagicMock()
        mock_anthropic_model = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "strands": mock_strands,
                "strands.models": MagicMock(),
                "strands.models.anthropic": mock_anthropic_model,
            },
        ):
            result = mod.run_check(ctx)

        assert result["passed"] is True
        assert "No spec references" in result["output"]


class TestSpecAlignmentWithMockedAgent:
    """Test spec-alignment with mocked Strands Agent returning structured results."""

    def test_passing_evaluation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module(SPEC_ALIGNMENT_PATH, "spec_alignment_check")
        _write_file(tmp_path, "src/main.py", "def greet(name: str) -> str:\n    return f'Hello {name}'")
        _write_file(tmp_path, "docs/spec.md", "# Greeting API\nMust accept name parameter.")

        ctx = _make_context(
            tmp_path,
            changed_files=["src/main.py"],
            spec_refs=["docs/spec.md"],
        )

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        ai_response = json.dumps(
            {
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
        )

        mock_agent_instance = MagicMock()
        mock_agent_instance.return_value = ai_response
        mock_agent_cls = MagicMock(return_value=mock_agent_instance)
        mock_anthropic_model_cls = MagicMock()

        mock_strands_mod = types.ModuleType("strands")
        mock_strands_mod.Agent = mock_agent_cls
        mock_anthropic_mod = types.ModuleType("strands.models.anthropic")
        mock_anthropic_mod.AnthropicModel = mock_anthropic_model_cls

        with patch.dict(
            sys.modules,
            {
                "strands": mock_strands_mod,
                "strands.models": types.ModuleType("strands.models"),
                "strands.models.anthropic": mock_anthropic_mod,
            },
        ):
            result = mod.run_check(ctx)

        assert result["passed"] is True
        assert result["detail"]["overall_score"] == 9
        assert "9/10" in result["output"]
        mock_anthropic_model_cls.assert_called_once_with(
            client_args={"api_key": "test-key"},
            model_id="claude-sonnet-4-6",
            max_tokens=8192,
            params={"temperature": 0.0},
        )

    def test_failing_evaluation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module(SPEC_ALIGNMENT_PATH, "spec_alignment_check")
        _write_file(tmp_path, "src/main.py", "x = 1")
        _write_file(tmp_path, "docs/spec.md", "# Complex API spec")

        ctx = _make_context(
            tmp_path,
            changed_files=["src/main.py"],
            spec_refs=["docs/spec.md"],
        )

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        ai_response = json.dumps(
            {
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
        )

        mock_agent_instance = MagicMock()
        mock_agent_instance.return_value = ai_response
        mock_agent_cls = MagicMock(return_value=mock_agent_instance)
        mock_anthropic_model_cls = MagicMock()

        mock_strands_mod = types.ModuleType("strands")
        mock_strands_mod.Agent = mock_agent_cls
        mock_anthropic_mod = types.ModuleType("strands.models.anthropic")
        mock_anthropic_mod.AnthropicModel = mock_anthropic_model_cls

        with patch.dict(
            sys.modules,
            {
                "strands": mock_strands_mod,
                "strands.models": types.ModuleType("strands.models"),
                "strands.models.anthropic": mock_anthropic_mod,
            },
        ):
            result = mod.run_check(ctx)

        assert result["passed"] is False
        assert result["detail"]["overall_score"] == 3


# ---------------------------------------------------------------------------
# AI code review tests
# ---------------------------------------------------------------------------


class TestAiCodeReviewSkips:
    """Test graceful skip conditions for ai-code-review."""

    def test_skip_when_strands_not_installed(self, tmp_path: Path) -> None:
        mod = _load_check_module(AI_CODE_REVIEW_PATH, "ai_code_review_check")
        ctx = _make_context(tmp_path, changed_files=["src/main.py"])

        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name in ("strands", "strands.models.anthropic"):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = mod.run_check(ctx)

        assert result["passed"] is True
        assert "SKIPPED" in result["output"]
        assert "strands-agents not installed" in result["output"]
        assert result["detail"]["skipped"] is True

    def test_skip_when_api_key_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module(AI_CODE_REVIEW_PATH, "ai_code_review_check")
        ctx = _make_context(tmp_path, changed_files=["src/main.py"])
        _write_file(tmp_path, "src/main.py", "print('hello')")

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        mock_strands = MagicMock()
        mock_anthropic_model = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "strands": mock_strands,
                "strands.models": MagicMock(),
                "strands.models.anthropic": mock_anthropic_model,
            },
        ):
            result = mod.run_check(ctx)

        assert result["passed"] is True
        assert "SKIPPED" in result["output"]
        assert "ANTHROPIC_API_KEY not configured" in result["output"]

    def test_skip_when_no_changed_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module(AI_CODE_REVIEW_PATH, "ai_code_review_check")
        ctx = _make_context(tmp_path, changed_files=[])

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        mock_strands = MagicMock()
        mock_anthropic_model = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "strands": mock_strands,
                "strands.models": MagicMock(),
                "strands.models.anthropic": mock_anthropic_model,
            },
        ):
            result = mod.run_check(ctx)

        assert result["passed"] is True
        assert "No changed files" in result["output"]


class TestAiCodeReviewWithMockedAgent:
    """Test ai-code-review with mocked Strands Agent."""

    def test_clean_review_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module(AI_CODE_REVIEW_PATH, "ai_code_review_check")
        _write_file(tmp_path, "src/main.py", "def safe_func() -> str:\n    return 'ok'")

        ctx = _make_context(tmp_path, changed_files=["src/main.py"])

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        ai_response = json.dumps(
            {
                "findings": [],
                "summary": "No issues found.",
                "passed": True,
            }
        )

        mock_agent_instance = MagicMock()
        mock_agent_instance.return_value = ai_response
        mock_agent_cls = MagicMock(return_value=mock_agent_instance)
        mock_anthropic_model_cls = MagicMock()

        mock_strands_mod = types.ModuleType("strands")
        mock_strands_mod.Agent = mock_agent_cls
        mock_anthropic_mod = types.ModuleType("strands.models.anthropic")
        mock_anthropic_mod.AnthropicModel = mock_anthropic_model_cls

        with patch.dict(
            sys.modules,
            {
                "strands": mock_strands_mod,
                "strands.models": types.ModuleType("strands.models"),
                "strands.models.anthropic": mock_anthropic_mod,
            },
        ):
            result = mod.run_check(ctx)

        assert result["passed"] is True
        assert result["detail"]["critical_count"] == 0
        assert "No issues found" in result["output"]

    def test_critical_finding_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module(AI_CODE_REVIEW_PATH, "ai_code_review_check")
        _write_file(tmp_path, "src/main.py", "password = 'hunter2'")

        ctx = _make_context(tmp_path, changed_files=["src/main.py"])

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        ai_response = json.dumps(
            {
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
        )

        mock_agent_instance = MagicMock()
        mock_agent_instance.return_value = ai_response
        mock_agent_cls = MagicMock(return_value=mock_agent_instance)
        mock_anthropic_model_cls = MagicMock()

        mock_strands_mod = types.ModuleType("strands")
        mock_strands_mod.Agent = mock_agent_cls
        mock_anthropic_mod = types.ModuleType("strands.models.anthropic")
        mock_anthropic_mod.AnthropicModel = mock_anthropic_model_cls

        with patch.dict(
            sys.modules,
            {
                "strands": mock_strands_mod,
                "strands.models": types.ModuleType("strands.models"),
                "strands.models.anthropic": mock_anthropic_mod,
            },
        ):
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

        ai_response = json.dumps(
            {
                "findings": [
                    {
                        "severity": "warning",
                        "category": "quality",
                        "file": "src/main.py",
                        "description": "Variable name too short",
                        "suggestion": "Use descriptive name",
                    }
                ],
                "summary": "Minor quality issue.",
                "passed": True,
            }
        )

        mock_agent_instance = MagicMock()
        mock_agent_instance.return_value = ai_response
        mock_agent_cls = MagicMock(return_value=mock_agent_instance)
        mock_anthropic_model_cls = MagicMock()

        mock_strands_mod = types.ModuleType("strands")
        mock_strands_mod.Agent = mock_agent_cls
        mock_anthropic_mod = types.ModuleType("strands.models.anthropic")
        mock_anthropic_mod.AnthropicModel = mock_anthropic_model_cls

        with patch.dict(
            sys.modules,
            {
                "strands": mock_strands_mod,
                "strands.models": types.ModuleType("strands.models"),
                "strands.models.anthropic": mock_anthropic_mod,
            },
        ):
            result = mod.run_check(ctx)

        assert result["passed"] is True
        assert result["detail"]["warning_count"] == 1
        assert result["detail"]["critical_count"] == 0

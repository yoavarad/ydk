"""Tests for the YAML-based reviewer agent framework."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path  # noqa: TC003
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ydk.core.reviewer import (
    ReviewerAgent,
    ReviewerConfig,
    ReviewResult,
    _compile_tool,
    load_all_reviewers,
    load_reviewer,
    run_all_sync,
)


def _dummy_tool(text: str) -> str:
    """A dummy deterministic tool that always finds one issue."""
    return json.dumps([{"line": 1, "text": "test finding", "category": "test"}])


def _empty_tool(text: str) -> str:
    """A dummy tool that finds nothing."""
    return json.dumps([])


def _make_config(**overrides: object) -> ReviewerConfig:
    """Create a ReviewerConfig with sensible defaults."""
    defaults: dict[str, object] = {
        "id": "T01",
        "name": "Test Reviewer",
        "system_prompt": "You are a test reviewer.",
        "tools": [_dummy_tool],
        "threshold": 8,
        "group": "quality",
    }
    defaults.update(overrides)
    return ReviewerConfig(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


class TestCompileTool:
    def test_compile_simple_tool(self) -> None:
        tool_def = {
            "name": "hello",
            "code": textwrap.dedent("""\
                def hello(text: str) -> str:
                    return f"hello {text}"
            """),
        }
        fn = _compile_tool(tool_def)
        assert callable(fn)
        assert fn("world") == "hello world"

    def test_compile_tool_with_imports(self) -> None:
        tool_def = {
            "name": "scan",
            "code": textwrap.dedent("""\
                def scan(text: str) -> str:
                    import json
                    return json.dumps([{"found": True}])
            """),
        }
        fn = _compile_tool(tool_def)
        result = json.loads(fn("test"))
        assert result == [{"found": True}]

    def test_compile_tool_missing_function_raises(self) -> None:
        tool_def = {
            "name": "missing",
            "code": "x = 42\n",
        }
        with pytest.raises(ValueError, match="did not define a function named 'missing'"):
            _compile_tool(tool_def)


class TestLoadReviewer:
    def test_load_from_yaml(self, tmp_path: Path) -> None:
        yaml_content = textwrap.dedent("""\
            id: T01
            name: Test Reviewer
            group: quality
            threshold: 7
            tools:
              - name: greet
                description: A greeting tool
                code: |
                  def greet(text: str) -> str:
                      return "hello"
            system_prompt: You are a test reviewer.
        """)
        yaml_file = tmp_path / "t01.yaml"
        yaml_file.write_text(yaml_content)

        config = load_reviewer(yaml_file)
        assert config.id == "T01"
        assert config.name == "Test Reviewer"
        assert config.threshold == 7
        assert config.group == "quality"
        assert len(config.tools) == 1
        assert config.tools[0]("x") == "hello"

    def test_load_with_bad_tool_still_loads(self, tmp_path: Path) -> None:
        yaml_content = textwrap.dedent("""\
            id: T02
            name: Bad Tool Reviewer
            group: quality
            threshold: 8
            tools:
              - name: broken
                description: A broken tool
                code: |
                  raise SyntaxError("bad")
            system_prompt: You are a test reviewer.
        """)
        yaml_file = tmp_path / "t02.yaml"
        yaml_file.write_text(yaml_content)

        config = load_reviewer(yaml_file)
        assert config.id == "T02"
        assert len(config.tools) == 0  # Tool failed to compile, skipped

    def test_load_defaults(self, tmp_path: Path) -> None:
        yaml_content = textwrap.dedent("""\
            id: T03
            name: Minimal
            tools: []
            system_prompt: You are a reviewer.
        """)
        yaml_file = tmp_path / "t03.yaml"
        yaml_file.write_text(yaml_content)

        config = load_reviewer(yaml_file)
        assert config.threshold == 8
        assert config.group == "quality"


class TestLoadAllReviewers:
    def test_loads_all_yaml_files(self, tmp_path: Path) -> None:
        for i in range(1, 4):
            (tmp_path / f"n{i:02d}.yaml").write_text(
                textwrap.dedent(f"""\
                    id: N{i:02d}
                    name: Reviewer {i}
                    group: quality
                    threshold: 8
                    tools: []
                    system_prompt: Review criterion {i}.
                """)
            )

        configs = load_all_reviewers(tmp_path)
        assert len(configs) == 3
        assert [c.id for c in configs] == ["N01", "N02", "N03"]

    def test_threshold_overrides_apply(self, tmp_path: Path) -> None:
        (tmp_path / "n01.yaml").write_text(
            textwrap.dedent("""\
                id: N01
                name: Test
                group: completeness
                threshold: 8
                tools: []
                system_prompt: Review.
            """)
        )

        configs = load_all_reviewers(tmp_path, threshold_overrides={"completeness": 6})
        assert configs[0].threshold == 6

    def test_skips_bad_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "good.yaml").write_text(
            textwrap.dedent("""\
                id: G01
                name: Good
                group: quality
                threshold: 8
                tools: []
                system_prompt: Good reviewer.
            """)
        )
        (tmp_path / "bad.yaml").write_text("not: valid: yaml: [[[")

        configs = load_all_reviewers(tmp_path)
        assert len(configs) == 1
        assert configs[0].id == "G01"


class TestLoadBuiltInReviewers:
    """Test that the shipped YAML files all load correctly."""

    def test_loads_10_reviewers(self) -> None:
        from ydk.spec_reviewers import REVIEWERS_DIR

        configs = load_all_reviewers(REVIEWERS_DIR)
        assert len(configs) == 10

    def test_all_ids_present(self) -> None:
        from ydk.spec_reviewers import REVIEWERS_DIR

        configs = load_all_reviewers(REVIEWERS_DIR)
        ids = {c.id for c in configs}
        expected = {f"N{i:02d}" for i in range(1, 11)}
        assert ids == expected

    def test_all_have_system_prompts(self) -> None:
        from ydk.spec_reviewers import REVIEWERS_DIR

        configs = load_all_reviewers(REVIEWERS_DIR)
        for c in configs:
            assert len(c.system_prompt) > 100, f"{c.id} has too short a system prompt"

    def test_tools_are_callable(self) -> None:
        from ydk.spec_reviewers import REVIEWERS_DIR

        configs = load_all_reviewers(REVIEWERS_DIR)
        for c in configs:
            for tool in c.tools:
                assert callable(tool), f"{c.id} has non-callable tool"

    def test_all_tools_execute(self) -> None:
        """All compiled tools can execute on a trivial input."""
        from ydk.spec_reviewers import REVIEWERS_DIR

        configs = load_all_reviewers(REVIEWERS_DIR)
        for c in configs:
            for tool in c.tools:
                result = tool("The system handles orders.")
                # Should return valid JSON
                parsed = json.loads(result)
                assert isinstance(parsed, (list, dict)), f"{c.id}/{tool.__name__} returned non-JSON"


# ---------------------------------------------------------------------------
# ReviewerAgent
# ---------------------------------------------------------------------------


class TestReviewerConfig:
    def test_create_config(self) -> None:
        config = _make_config()
        assert config.id == "T01"
        assert config.name == "Test Reviewer"
        assert config.threshold == 8
        assert config.group == "quality"
        assert len(config.tools) == 1

    def test_config_is_frozen(self) -> None:
        config = _make_config()
        with pytest.raises(AttributeError):
            config.id = "T02"  # type: ignore[misc]


class TestReviewerAgentToolsOnly:
    """Test the ReviewerAgent in tools-only mode (no LLM)."""

    def test_tools_only_with_findings(self) -> None:
        config = _make_config(tools=[_dummy_tool])
        agent = ReviewerAgent(config=config, model_config={})
        result = agent._run_tools_only("some spec content")
        assert result.reviewer_id == "T01"
        assert result.score == 7  # 1 finding -> score 7
        assert len(result.findings) == 1
        assert "test finding" in result.findings[0]["text"]

    def test_tools_only_no_findings(self) -> None:
        config = _make_config(tools=[_empty_tool])
        agent = ReviewerAgent(config=config, model_config={})
        result = agent._run_tools_only("clean spec content")
        assert result.score == 10
        assert result.passed is True
        assert len(result.findings) == 0

    def test_tools_only_many_findings(self) -> None:
        def many_findings_tool(text: str) -> str:
            return json.dumps([{"line": i, "text": f"issue {i}", "category": "test"} for i in range(15)])

        config = _make_config(tools=[many_findings_tool])
        agent = ReviewerAgent(config=config, model_config={})
        result = agent._run_tools_only("spec with many issues")
        assert result.score == 2  # 15 findings -> score 2
        assert result.passed is False

    def test_tools_only_falls_back_on_tool_error(self) -> None:
        def broken_tool(text: str) -> str:
            raise RuntimeError("tool crashed")

        config = _make_config(tools=[broken_tool])
        agent = ReviewerAgent(config=config, model_config={})
        result = agent._run_tools_only("spec content")
        assert result.score == 10  # No findings collected
        assert len(result.findings) == 0


class TestReviewerAgentParsing:
    """Test JSON response parsing."""

    def test_parse_valid_json(self) -> None:
        config = _make_config()
        agent = ReviewerAgent(config=config, model_config={})

        response = json.dumps(
            {
                "score": 9,
                "reasoning": "Well written spec.",
                "suggestions": ["Minor improvement possible."],
                "findings": [{"line": 5, "text": "minor issue", "issue": "could be clearer"}],
            }
        )

        result = agent._parse_response(response)
        assert result.score == 9
        assert result.passed is True
        assert result.reasoning == "Well written spec."
        assert len(result.suggestions) == 1
        assert len(result.findings) == 1

    def test_parse_json_with_markdown_fences(self) -> None:
        config = _make_config()
        agent = ReviewerAgent(config=config, model_config={})

        response = '```json\n{"score": 6, "reasoning": "Needs work.", "suggestions": [], "findings": []}\n```'
        result = agent._parse_response(response)
        assert result.score == 6

    def test_parse_json_embedded_in_text(self) -> None:
        config = _make_config()
        agent = ReviewerAgent(config=config, model_config={})

        response = 'Here is my review:\n{"score": 8, "reasoning": "Good.", "suggestions": [], "findings": []}\nDone.'
        result = agent._parse_response(response)
        assert result.score == 8

    def test_parse_unparseable_returns_fallback(self) -> None:
        config = _make_config()
        agent = ReviewerAgent(config=config, model_config={})

        result = agent._parse_response("This is not JSON at all.")
        assert result.score == 0
        assert result.passed is False
        assert "Failed to parse" in result.reasoning


class TestRunWithLlm:
    """Test _run_with_llm calls Anthropic Messages API with a forced tool_choice."""

    def _mock_tool_use_response(self, **overrides: object) -> SimpleNamespace:
        data = {
            "score": 9,
            "reasoning": "Well written spec.",
            "suggestions": ["Minor improvement possible."],
            "findings": [{"line": 5, "text": "minor issue", "issue": "could be clearer"}],
        }
        data.update(overrides)
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=data)])

    def test_calls_messages_create_with_forced_tool_choice(self) -> None:
        config = _make_config(tools=[_empty_tool])
        agent = ReviewerAgent(config=config, model_config={"model_id": "claude-sonnet-4-6", "api_key": None})

        with patch("ydk.core.reviewer.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = self._mock_tool_use_response()

            result = agent._run_with_llm("some spec content")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["tool_choice"] == {"type": "tool", "name": "submit_review"}
        assert result.score == 9
        assert result.reasoning == "Well written spec."
        assert len(result.findings) == 1

    def test_parses_tool_use_block_into_review_result(self) -> None:
        config = _make_config(tools=[_empty_tool])
        agent = ReviewerAgent(config=config, model_config={"model_id": "claude-sonnet-4-6", "api_key": None})

        with patch("ydk.core.reviewer.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = self._mock_tool_use_response(score=6, reasoning="Needs work.")

            result = agent._run_with_llm("some spec content")

        assert result.reviewer_id == "T01"
        assert result.score == 6
        assert result.passed is False  # 6 < threshold 8


class TestReviewerAgentGracefulDegradation:
    """Test that the agent falls back to tools-only when LLM is unavailable."""

    def test_review_falls_back_to_tools_on_import_error(self) -> None:
        config = _make_config(tools=[_empty_tool])
        agent = ReviewerAgent(config=config, model_config={})

        with patch.object(agent, "_run_with_llm", side_effect=ImportError("no strands")):
            result = agent.review("spec content")

        assert result.score == 10
        assert "Deterministic scan" in result.reasoning

    def test_review_falls_back_on_credential_error(self) -> None:
        config = _make_config(tools=[_dummy_tool])
        agent = ReviewerAgent(config=config, model_config={})

        with patch.object(agent, "_run_with_llm", side_effect=RuntimeError("no credentials")):
            result = agent.review("spec content")

        assert result.reviewer_id == "T01"
        assert result.score == 7  # 1 finding from dummy tool


# ---------------------------------------------------------------------------
# run_all_sync
# ---------------------------------------------------------------------------


class TestCompileToolStrandsWrapping:
    """Verify _compile_tool wraps functions with the Strands @tool decorator."""

    def test_compiled_tool_is_strands_decorated(self) -> None:
        """When strands is installed, compiled tools should be DecoratedFunctionTool."""
        from strands.tools.decorator import DecoratedFunctionTool

        tool_def = {
            "name": "greet",
            "description": "Greet someone",
            "code": textwrap.dedent("""\
                def greet(text: str) -> str:
                    return f"hi {text}"
            """),
        }
        fn = _compile_tool(tool_def)
        assert isinstance(fn, DecoratedFunctionTool)
        # Should still be callable as a normal function
        assert fn("alice") == "hi alice"

    def test_compiled_tool_preserves_name_and_description(self) -> None:
        from strands.tools.decorator import DecoratedFunctionTool

        tool_def = {
            "name": "scanner",
            "description": "Scans text for issues",
            "code": textwrap.dedent("""\
                def scanner(text: str) -> str:
                    import json
                    return json.dumps([])
            """),
        }
        fn = _compile_tool(tool_def)
        assert isinstance(fn, DecoratedFunctionTool)
        assert fn.tool_name == "scanner"


class TestOutputCapture:
    """Verify that concurrent reviewer output is captured, not printed."""

    def test_run_reviewer_captures_stdout(self) -> None:
        """run_reviewer should capture agent stdout so parallel runs don't garble."""
        import io
        import sys

        from ydk.core.reviewer import run_reviewer

        config = _make_config(tools=[_empty_tool])

        # Patch _run_with_llm to print to stdout (simulating Strands streaming)
        def _noisy_review(self: object, spec_content: str) -> ReviewResult:
            print("STREAMING OUTPUT THAT SHOULD BE CAPTURED")
            return ReviewResult(reviewer_id="T01", name="Test Reviewer", score=10, passed=True, reasoning="Good.")

        captured_terminal = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured_terminal
        try:
            with patch.object(ReviewerAgent, "review", _noisy_review):
                result = run_reviewer(config, "spec content", {})
        finally:
            sys.stdout = old_stdout

        # The noisy output should NOT have reached the real terminal
        assert "STREAMING OUTPUT" not in captured_terminal.getvalue()
        # But it should be in debug_output
        assert "STREAMING OUTPUT" in result.debug_output


class TestRunAllSync:
    def test_runs_all_reviewers(self, tmp_path: Path) -> None:
        for i in range(1, 3):
            (tmp_path / f"r{i:02d}.yaml").write_text(
                textwrap.dedent(f"""\
                    id: R{i:02d}
                    name: Reviewer {i}
                    group: quality
                    threshold: 8
                    tools:
                      - name: noop
                        description: No-op tool
                        code: |
                          def noop(text: str) -> str:
                              import json
                              return json.dumps([])
                    system_prompt: Review criterion {i}.
                """)
            )

        with patch.object(ReviewerAgent, "review") as mock_review:
            mock_review.side_effect = [
                ReviewResult(reviewer_id="R01", name="Reviewer 1", score=10, passed=True, reasoning="Good."),
                ReviewResult(reviewer_id="R02", name="Reviewer 2", score=5, passed=False, reasoning="Issues."),
            ]
            results = run_all_sync("spec content", tmp_path)

        assert len(results) == 2
        assert results[0].reviewer_id == "R01"
        assert results[1].reviewer_id == "R02"

    def test_handles_reviewer_exceptions(self, tmp_path: Path) -> None:
        (tmp_path / "r01.yaml").write_text(
            textwrap.dedent("""\
                id: R01
                name: Failing
                group: quality
                threshold: 8
                tools: []
                system_prompt: Review.
            """)
        )

        with patch.object(ReviewerAgent, "review", side_effect=RuntimeError("crash")):
            results = run_all_sync("spec content", tmp_path)

        assert len(results) == 1
        assert results[0].score == 0
        assert results[0].passed is False

    def test_rubric_filter(self, tmp_path: Path) -> None:
        (tmp_path / "a.yaml").write_text(
            textwrap.dedent("""\
                id: A01
                name: A
                group: completeness
                threshold: 8
                tools: []
                system_prompt: Review.
            """)
        )
        (tmp_path / "b.yaml").write_text(
            textwrap.dedent("""\
                id: B01
                name: B
                group: quality
                threshold: 8
                tools: []
                system_prompt: Review.
            """)
        )

        with patch.object(ReviewerAgent, "review") as mock_review:
            mock_review.return_value = ReviewResult(
                reviewer_id="A01", name="A", score=10, passed=True, reasoning="Good."
            )
            results = run_all_sync("spec", tmp_path, rubric_filter="completeness")

        assert len(results) == 1
        assert results[0].reviewer_id == "A01"

"""Tests for the YAML-based reviewer agent framework."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path  # noqa: TC003

import pytest

from ydk.core.reviewer import (
    ReviewerConfig,
    _compile_tool,
    load_all_reviewers,
    load_reviewer,
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
        assert config.model_tier == "review"


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


class TestModelTiers:
    def test_built_in_reviewers_use_a_configured_tier(self) -> None:
        from ydk.models.config import DEFAULT_MODEL_TIERS
        from ydk.spec_reviewers import REVIEWERS_DIR

        reviewers = load_all_reviewers(REVIEWERS_DIR)
        assert reviewers
        assert {r.model_tier for r in reviewers} <= set(DEFAULT_MODEL_TIERS)


class TestPerReviewerFallbackRemoved:
    def test_unreachable_per_reviewer_llm_path_is_gone(self) -> None:
        import ydk.core.reviewer as reviewer_mod

        for name in ("ReviewerAgent", "run_reviewer", "run_all_sync"):
            assert not hasattr(reviewer_mod, name), name

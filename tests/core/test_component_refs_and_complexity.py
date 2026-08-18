"""Tests for --component-refs flag and analyze-complexity LLM provider wiring."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from ydk.core.complexity_scorer import ComplexityScorer
from ydk.models.pm import TaskCreate, TaskDetail


class TestComponentRefs:
    def test_task_create_has_component_refs(self) -> None:
        task = TaskCreate(
            title="Implement order model",
            story_id="S-001",
            component_refs=["ydk:entity:orders/Order", "ydk:route:orders/create"],
        )
        assert task.component_refs == ["ydk:entity:orders/Order", "ydk:route:orders/create"]

    def test_task_create_component_refs_defaults_empty(self) -> None:
        task = TaskCreate(title="Simple task")
        assert task.component_refs == []

    def test_task_detail_has_component_refs(self) -> None:
        detail = TaskDetail(
            title="Implement order model",
            component_refs=["ydk:entity:orders/Order"],
        )
        assert detail.component_refs == ["ydk:entity:orders/Order"]

    def test_task_detail_component_refs_defaults_empty(self) -> None:
        detail = TaskDetail(title="Simple task")
        assert detail.component_refs == []


class TestComponentRefsInFrontmatter:
    def test_component_refs_stored_in_frontmatter(self, tmp_path: object) -> None:
        """component_refs should appear in the YAML frontmatter of task files."""
        from pathlib import Path

        from ydk.repositories.local.tasks import LocalTaskRepository

        tasks_root = Path(str(tmp_path))
        (tasks_root / "manifest.yaml").write_text("tasks: {}\nstories: {}\nepics: {}\n")

        repo = LocalTaskRepository(tasks_root)
        task = TaskCreate(
            title="Test task",
            component_refs=["ydk:entity:Foo", "ydk:route:bar/create"],
        )
        detail = repo.create_task(task)

        assert detail.component_refs == ["ydk:entity:Foo", "ydk:route:bar/create"]

        # Read it back
        loaded = repo.get_task(detail.id)
        assert loaded.component_refs == ["ydk:entity:Foo", "ydk:route:bar/create"]


class TestComponentRefsInGitHubParser:
    def test_render_and_parse_component_refs(self) -> None:
        from ydk.repositories.github.parser import parse_task_detail, render_task_body

        task = TaskCreate(
            title="Test",
            component_refs=["ydk:entity:Order", "ydk:route:create"],
            spec_refs=["orders.md"],
        )
        body = render_task_body(task)
        assert "**Component refs**:" in body
        assert "ydk:entity:Order" in body

        detail = parse_task_detail(
            number=42,
            title="Test",
            body=body,
            state="OPEN",
            labels=["task"],
        )
        assert detail.component_refs == ["ydk:entity:Order", "ydk:route:create"]


class TestAnalyzeComplexityProvider:
    def test_no_provider_returns_default_score(self) -> None:
        scorer = ComplexityScorer(llm_provider=None)
        task = TaskDetail(title="Some task", id="T-001")
        result = scorer.score_task(task)
        assert result.score == 5
        assert "No LLM provider" in result.reasoning

    def test_provider_invoked_with_prompt(self) -> None:
        mock_provider = MagicMock()
        mock_provider.invoke.return_value = json.dumps(
            {"score": 7, "reasoning": "Cross-cutting concern", "should_expand": False, "suggested_splits": []}
        )
        scorer = ComplexityScorer(llm_provider=mock_provider)
        task = TaskDetail(title="Complex task", id="T-042", description="Touches many files")
        result = scorer.score_task(task)
        assert result.score == 7
        assert result.reasoning == "Cross-cutting concern"
        mock_provider.invoke.assert_called_once()

    def test_get_llm_provider_uses_aws_config(self) -> None:
        """_get_llm_provider should create a boto3 session with the configured profile."""
        import sys

        mock_boto3 = MagicMock()
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_boto3.Session.return_value = mock_session
        mock_session.client.return_value = mock_client

        with patch.dict(sys.modules, {"boto3": mock_boto3}), patch("ydk.core.config.load_config") as mock_load:
            mock_cfg = MagicMock()
            mock_cfg.aws.profile = "my-test-profile"
            mock_cfg.aws.region = "us-west-2"
            mock_cfg.ai.model_tiers = {"fast": "us.anthropic.claude-sonnet-4-20250514-v1:0"}
            mock_load.return_value = mock_cfg

            from ydk.cli.task_cmd import _get_llm_provider

            provider = _get_llm_provider()

        assert provider is not None
        mock_boto3.Session.assert_called_once_with(
            profile_name="my-test-profile",
            region_name="us-west-2",
        )
        mock_session.client.assert_called_once_with("bedrock-runtime")

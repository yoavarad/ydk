"""Tests for ydk task analyze-complexity CLI command."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ydk.cli import app
from ydk.models.complexity import ComplexityScore
from ydk.models.pm import TaskDetail, TaskSummary

runner = CliRunner()


def _make_task_detail(task_id: str = "T-001", title: str = "Test task") -> TaskDetail:
    return TaskDetail(id=task_id, title=title, description="A test task")


def _make_score(task_id: str = "T-001", score: int = 6) -> ComplexityScore:
    return ComplexityScore(task_id=task_id, score=score, reasoning="Moderate")


class _FakeRepo:
    """Fake repository for CLI tests."""

    def __init__(self, tasks: list[TaskDetail] | None = None) -> None:
        self._tasks = {t.id: t for t in (tasks or [])}

    def get_task(self, task_id: str) -> TaskDetail:
        if task_id not in self._tasks:
            raise FileNotFoundError(f"Task {task_id} not found")
        return self._tasks[task_id]

    def list_tasks(self, state: str = "open") -> list[TaskSummary]:
        return [
            TaskSummary(id=t.id, title=t.title, status=t.status)
            for t in self._tasks.values()
            if state == "all" or t.status == state
        ]


class _FakeScorer:
    """Fake scorer that returns canned results."""

    def __init__(self, scores: list[ComplexityScore]) -> None:
        self._scores = scores
        self._idx = 0

    def score_task(self, task: TaskDetail, context: str | None = None) -> ComplexityScore:
        score = self._scores[self._idx % len(self._scores)]
        self._idx += 1
        return score

    def score_tasks(self, tasks: list[TaskDetail], context: str | None = None) -> list[ComplexityScore]:
        return [self.score_task(t) for t in tasks]


def _patch_for_cli(repo: _FakeRepo, scorer: _FakeScorer, llm_provider: object | None = None):
    """Return combined patch context managers for the CLI command."""
    return (
        patch("ydk.cli.task_cmd._get_repo", return_value=repo),
        patch("ydk.core.llm_provider.get_llm_provider", return_value=llm_provider),
        patch("ydk.core.complexity_scorer.ComplexityScorer", return_value=scorer),
    )


class TestAnalyzeComplexityOutput:
    """Test that CLI renders the table correctly."""

    def test_single_task_output(self) -> None:
        task = _make_task_detail("T-001", "Add login")
        score = _make_score("T-001", 8)
        repo = _FakeRepo([task])
        scorer = _FakeScorer([score])

        p1, p2, p3 = _patch_for_cli(repo, scorer)
        with p1, p2, p3:
            result = runner.invoke(app, ["task", "analyze-complexity", "--task-id", "T-001"])

        assert result.exit_code == 0
        assert "T-001" in result.output

    def test_no_tasks_message(self) -> None:
        repo = _FakeRepo([])
        scorer = _FakeScorer([_make_score()])

        p1, p2, p3 = _patch_for_cli(repo, scorer)
        with p1, p2, p3:
            result = runner.invoke(app, ["task", "analyze-complexity"])

        assert result.exit_code == 0
        assert "No tasks to analyze" in result.output

    def test_json_output(self) -> None:
        task = _make_task_detail("T-001", "Add login")
        score = _make_score("T-001", 3)
        repo = _FakeRepo([task])
        scorer = _FakeScorer([score])

        p1, p2, p3 = _patch_for_cli(repo, scorer)
        with p1, p2, p3:
            result = runner.invoke(app, ["--format", "json", "task", "analyze-complexity", "--task-id", "T-001"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["score"] == 3


class TestAnalyzeComplexityProviderWiring:
    """Test that analyze_complexity routes through ydk.core.llm_provider.get_llm_provider."""

    def test_none_provider_still_scores(self) -> None:
        """When get_llm_provider returns None, the CLI still produces default scores."""
        task = _make_task_detail("T-001", "Add login")
        score = _make_score("T-001", 5)
        repo = _FakeRepo([task])
        scorer = _FakeScorer([score])

        with (
            patch("ydk.cli.task_cmd._get_repo", return_value=repo),
            patch("ydk.core.llm_provider.get_llm_provider", return_value=None) as mock_get_provider,
            patch("ydk.core.complexity_scorer.ComplexityScorer", return_value=scorer) as mock_scorer_cls,
        ):
            result = runner.invoke(app, ["task", "analyze-complexity", "--task-id", "T-001"])

        assert result.exit_code == 0
        mock_get_provider.assert_called_once()
        assert mock_scorer_cls.call_args.kwargs["llm_provider"] is None

    def test_working_provider_is_passed_to_scorer(self) -> None:
        """When get_llm_provider returns a provider, it is forwarded to ComplexityScorer."""
        task = _make_task_detail("T-001", "Add login")
        score = _make_score("T-001", 8)
        repo = _FakeRepo([task])
        scorer = _FakeScorer([score])
        fake_provider = MagicMock()
        fake_provider.invoke.return_value = "some response"

        with (
            patch("ydk.cli.task_cmd._get_repo", return_value=repo),
            patch("ydk.core.llm_provider.get_llm_provider", return_value=fake_provider) as mock_get_provider,
            patch("ydk.core.complexity_scorer.ComplexityScorer", return_value=scorer) as mock_scorer_cls,
        ):
            result = runner.invoke(app, ["task", "analyze-complexity", "--task-id", "T-001"])

        assert result.exit_code == 0
        mock_get_provider.assert_called_once()
        assert mock_scorer_cls.call_args.kwargs["llm_provider"] is fake_provider

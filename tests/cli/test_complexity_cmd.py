"""Tests for odk task analyze-complexity CLI command."""

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from odk.cli import app
from odk.models.complexity import ComplexityScore
from odk.models.pm import TaskDetail, TaskSummary

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


def _patch_for_cli(repo: _FakeRepo, scorer: _FakeScorer):
    """Return combined patch context managers for the CLI command."""
    return (
        patch("odk.cli.task_cmd._get_repo", return_value=repo),
        patch("odk.cli.task_cmd._get_llm_provider", return_value=None),
        patch("odk.core.complexity_scorer.ComplexityScorer", return_value=scorer),
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

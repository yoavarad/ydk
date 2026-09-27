"""Tests for `ydk task epics` and `ydk task stories` CLI commands."""

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from ydk.cli import app
from ydk.models.pm import EpicSummary, StorySummary, TaskDetail, TaskSummary

runner = CliRunner()


def _fake_epics() -> list[EpicSummary]:
    return [
        EpicSummary(id="E-001", title="Epic one", status="open"),
        EpicSummary(id="E-002", title="Epic two", status="closed"),
        EpicSummary(id="E-003", title="Epic three (no stories)", status="open"),
    ]


def _fake_stories(epic_id: str | None = None) -> list[StorySummary]:
    stories = [
        StorySummary(id="S-001", title="Story one", epic_id="E-001", status="open"),
        StorySummary(id="S-002", title="Story two", epic_id="E-002", status="closed"),
        StorySummary(id="S-003", title="Story three (no tasks)", epic_id="E-002", status="open"),
    ]
    if epic_id is None:
        return stories
    return [s for s in stories if s.epic_id == epic_id]


def _fake_tasks() -> list[TaskSummary]:
    return [
        TaskSummary(id="T-001", title="Task one", status="done"),
        TaskSummary(id="T-002", title="Task two", status="open"),
        TaskSummary(id="T-003", title="Task three", status="open"),
        TaskSummary(id="T-004", title="Orphan task", status="open"),
    ]


def _fake_task_detail(task_id: str) -> TaskDetail:
    # T-004 is intentionally absent (unmapped -> story_id=None): an orphan task
    # not attached to any story, which must not count toward any progress total.
    story_by_task = {"T-001": "S-001", "T-002": "S-001", "T-003": "S-002"}
    return TaskDetail(id=task_id, title=task_id, story_id=story_by_task.get(task_id))


class TestTaskEpicsCli:
    def test_human_output_shows_table_with_progress(self) -> None:
        with (
            patch("ydk.cli.task_cmd._get_epic_repo") as mock_epic_repo,
            patch("ydk.cli.task_cmd._get_story_repo") as mock_story_repo,
            patch("ydk.cli.task_cmd._get_repo") as mock_task_repo,
        ):
            mock_epic_repo.return_value.list_epics.return_value = _fake_epics()
            mock_story_repo.return_value.list_stories.side_effect = _fake_stories
            mock_task_repo.return_value.list_tasks.return_value = _fake_tasks()
            mock_task_repo.return_value.get_task.side_effect = _fake_task_detail

            result = runner.invoke(app, ["task", "epics"])

        assert result.exit_code == 0
        assert "E-001" in result.output
        assert "Epic one" in result.output
        assert "1/2" in result.output  # E-001 -> S-001 -> T-001 (done), T-002 (open)
        assert "0/1" in result.output  # E-002 -> S-002 -> T-003 (open); S-003 has no tasks
        assert "0/0" in result.output  # E-003 has no stories at all

    def test_json_output(self) -> None:
        with (
            patch("ydk.cli.task_cmd._get_epic_repo") as mock_epic_repo,
            patch("ydk.cli.task_cmd._get_story_repo") as mock_story_repo,
            patch("ydk.cli.task_cmd._get_repo") as mock_task_repo,
        ):
            mock_epic_repo.return_value.list_epics.return_value = _fake_epics()
            mock_story_repo.return_value.list_stories.side_effect = _fake_stories
            mock_task_repo.return_value.list_tasks.return_value = _fake_tasks()
            mock_task_repo.return_value.get_task.side_effect = _fake_task_detail

            result = runner.invoke(app, ["--format", "json", "task", "epics"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 3
        assert data[0]["id"] == "E-001"
        assert data[0]["done"] == 1
        assert data[0]["total"] == 2

    def test_status_option_forwarded_to_repo(self) -> None:
        with patch("ydk.cli.task_cmd._get_epic_repo") as mock_epic_repo:
            mock_epic_repo.return_value.list_epics.return_value = []
            runner.invoke(app, ["task", "epics", "--status", "open"])
        mock_epic_repo.return_value.list_epics.assert_called_once_with(status="open")

    def test_empty_list(self) -> None:
        with patch("ydk.cli.task_cmd._get_epic_repo") as mock_epic_repo:
            mock_epic_repo.return_value.list_epics.return_value = []
            result = runner.invoke(app, ["task", "epics"])
        assert result.exit_code == 0
        assert "No epics found" in result.output


class TestTaskStoriesCli:
    def test_human_output_shows_table_with_progress(self) -> None:
        with (
            patch("ydk.cli.task_cmd._get_story_repo") as mock_story_repo,
            patch("ydk.cli.task_cmd._get_repo") as mock_task_repo,
        ):
            mock_story_repo.return_value.list_stories.side_effect = _fake_stories
            mock_task_repo.return_value.list_tasks.return_value = _fake_tasks()
            mock_task_repo.return_value.get_task.side_effect = _fake_task_detail

            result = runner.invoke(app, ["task", "stories"])

        assert result.exit_code == 0
        assert "S-001" in result.output
        assert "Story one" in result.output
        assert "1/2" in result.output  # S-001 -> T-001 (done), T-002 (open)
        assert "0/1" in result.output  # S-002 -> T-003 (open)
        assert "0/0" in result.output  # S-003 has no tasks at all (orphan task T-004 doesn't count)

    def test_filter_by_epic(self) -> None:
        with (
            patch("ydk.cli.task_cmd._get_story_repo") as mock_story_repo,
            patch("ydk.cli.task_cmd._get_repo") as mock_task_repo,
        ):
            mock_story_repo.return_value.list_stories.side_effect = _fake_stories
            mock_task_repo.return_value.list_tasks.return_value = _fake_tasks()
            mock_task_repo.return_value.get_task.side_effect = _fake_task_detail

            result = runner.invoke(app, ["task", "stories", "--epic", "E-001"])

        assert result.exit_code == 0
        assert "S-001" in result.output
        assert "S-002" not in result.output
        mock_story_repo.return_value.list_stories.assert_called_once_with(epic_id="E-001")

    def test_json_output(self) -> None:
        with (
            patch("ydk.cli.task_cmd._get_story_repo") as mock_story_repo,
            patch("ydk.cli.task_cmd._get_repo") as mock_task_repo,
        ):
            mock_story_repo.return_value.list_stories.side_effect = _fake_stories
            mock_task_repo.return_value.list_tasks.return_value = _fake_tasks()
            mock_task_repo.return_value.get_task.side_effect = _fake_task_detail

            result = runner.invoke(app, ["--format", "json", "task", "stories"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 3
        assert data[0]["id"] == "S-001"
        assert data[0]["done"] == 1
        assert data[0]["total"] == 2

    def test_empty_list(self) -> None:
        with patch("ydk.cli.task_cmd._get_story_repo") as mock_story_repo:
            mock_story_repo.return_value.list_stories.return_value = []
            result = runner.invoke(app, ["task", "stories"])
        assert result.exit_code == 0
        assert "No stories found" in result.output

"""Tests for the `ydk task sync` command (bulk task/PR status reconciliation)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from ydk.cli import app
from ydk.cli.task_cmd import task_app
from ydk.models.pm import EpicCreate, StoryCreate, TaskCreate, TaskSummary
from ydk.repositories.local.epics import LocalEpicRepository
from ydk.repositories.local.stories import LocalStoryRepository
from ydk.repositories.local.tasks import LocalTaskRepository

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def _summary(task_id: str, status: str) -> TaskSummary:
    return TaskSummary(id=task_id, title=f"Title {task_id}", status=status)


class TestTaskSyncCommand:
    def test_gh_absent_shows_message_and_never_touches_repo(self) -> None:
        with (
            patch("shutil.which", return_value=None),
            patch("ydk.cli.task_cmd._get_repo") as mock_get_repo,
        ):
            result = runner.invoke(task_app, ["sync"])
        assert result.exit_code == 0
        assert "gh" in result.output.lower()
        mock_get_repo.assert_not_called()

    def test_no_candidates_reports_clean_no_op(self) -> None:
        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = [
            _summary("T-001", "done"),
            _summary("T-002", "blocked-by-code"),
        ]
        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
        ):
            result = runner.invoke(task_app, ["sync"])
        assert result.exit_code == 0
        assert "No in-review or open tasks to reconcile." in result.output
        mock_repo.update_status.assert_not_called()

    def test_merged_pr_reconciles_task(self) -> None:
        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = [_summary("T-001", "in-review")]
        pr = {"number": 42, "state": "MERGED", "createdAt": "2026-01-01T00:00:00Z"}
        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.core.task_pr_lookup.list_prs", return_value=[pr]),
            patch("ydk.core.task_pr_lookup.find_task_pr", return_value=pr),
        ):
            result = runner.invoke(task_app, ["sync"])
        assert result.exit_code == 0
        mock_repo.update_status.assert_called_once_with("T-001", "done")
        assert "T-001" in result.output

    def test_open_pr_is_skipped_and_not_updated(self) -> None:
        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = [_summary("T-002", "open")]
        pr = {"number": 7, "state": "OPEN", "createdAt": "2026-01-01T00:00:00Z"}
        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.core.task_pr_lookup.list_prs", return_value=[pr]),
            patch("ydk.core.task_pr_lookup.find_task_pr", return_value=pr),
        ):
            result = runner.invoke(task_app, ["sync"])
        assert result.exit_code == 0
        mock_repo.update_status.assert_not_called()
        assert "not merged" in result.output.lower()

    def test_no_pr_found_is_skipped_and_not_updated(self) -> None:
        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = [_summary("T-003", "in-review")]
        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.core.task_pr_lookup.list_prs", return_value=[]),
            patch("ydk.core.task_pr_lookup.find_task_pr", return_value=None),
        ):
            result = runner.invoke(task_app, ["sync"])
        assert result.exit_code == 0
        mock_repo.update_status.assert_not_called()
        assert "no pr found" in result.output.lower()

    def test_mixed_candidates_partition_correctly_and_list_prs_called_once(self) -> None:
        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = [
            _summary("T-010", "in-review"),  # merged
            _summary("T-011", "open"),  # open pr
            _summary("T-012", "in-review"),  # no pr
            _summary("T-013", "done"),  # excluded entirely
            _summary("T-014", "in-progress"),  # excluded entirely
        ]
        merged_pr = {"number": 1, "state": "MERGED", "createdAt": "2026-01-01T00:00:00Z"}
        open_pr = {"number": 2, "state": "OPEN", "createdAt": "2026-01-01T00:00:00Z"}

        def fake_find_task_pr(task_id: str, prs: object = None) -> dict[str, object] | None:
            return {"T-010": merged_pr, "T-011": open_pr, "T-012": None}[task_id]

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.core.task_pr_lookup.list_prs", return_value=[merged_pr, open_pr]) as mock_list_prs,
            patch("ydk.core.task_pr_lookup.find_task_pr", side_effect=fake_find_task_pr) as mock_find,
        ):
            result = runner.invoke(task_app, ["sync"])
        assert result.exit_code == 0
        mock_list_prs.assert_called_once()
        assert mock_find.call_count == 3
        mock_repo.update_status.assert_called_once_with("T-010", "done")

    def test_update_status_failure_lands_in_skipped_and_loop_continues(self) -> None:
        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = [
            _summary("T-020", "in-review"),
            _summary("T-021", "in-review"),
        ]
        merged_pr = {"number": 5, "state": "MERGED", "createdAt": "2026-01-01T00:00:00Z"}
        mock_repo.update_status.side_effect = [RuntimeError("gh issue close failed"), None]
        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.core.task_pr_lookup.list_prs", return_value=[merged_pr]),
            patch("ydk.core.task_pr_lookup.find_task_pr", return_value=merged_pr),
        ):
            result = runner.invoke(task_app, ["sync"])
        assert result.exit_code == 0
        assert mock_repo.update_status.call_count == 2
        assert "gh issue close failed" in result.output

    def test_json_output_structure(self) -> None:
        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = [_summary("T-030", "in-review")]
        pr = {"number": 9, "state": "MERGED", "createdAt": "2026-01-01T00:00:00Z"}
        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.core.task_pr_lookup.list_prs", return_value=[pr]),
            patch("ydk.core.task_pr_lookup.find_task_pr", return_value=pr),
        ):
            result = runner.invoke(app, ["--format", "json", "task", "sync"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "reconciled" in data
        assert "skipped" in data
        assert len(data["reconciled"]) == 1
        assert data["reconciled"][0]["id"] == "T-030"


def _write_quick_task(task_id: str, status: str) -> Path:
    tasks_dir = Path(".ydk") / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    path = tasks_dir / f"{task_id}.md"
    path.write_text(
        f"---\nid: {task_id}\ntitle: t\nstatus: {status}\ntype: quickdev\n---\n\nbody\n",
        encoding="utf-8",
    )
    return path


class TestTaskSyncQuickTasks:
    def test_merged_pr_marks_in_progress_quick_task_done(self) -> None:
        path = _write_quick_task("QD-abc123", "in-progress")
        pr = {
            "number": 11,
            "state": "MERGED",
            "headRefName": "fix/qd-abc123-thing",
            "createdAt": "2026-01-01T00:00:00Z",
        }
        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = []
        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.core.task_pr_lookup.list_prs", return_value=[pr]),
        ):
            result = runner.invoke(task_app, ["sync"])
        assert result.exit_code == 0
        assert "QD-abc123" in result.output
        assert "status: done" in path.read_text(encoding="utf-8")
        mock_repo.update_status.assert_not_called()

    def test_unmerged_quick_task_left_unchanged(self) -> None:
        path = _write_quick_task("QD-def456", "in-progress")
        pr = {
            "number": 12,
            "state": "OPEN",
            "headRefName": "fix/qd-def456-thing",
            "createdAt": "2026-01-01T00:00:00Z",
        }
        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = []
        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.core.task_pr_lookup.list_prs", return_value=[pr]),
        ):
            result = runner.invoke(task_app, ["sync"])
        assert result.exit_code == 0
        assert "status: in-progress" in path.read_text(encoding="utf-8")
        assert "not merged" in result.output.lower()

    def test_done_quick_task_ignored(self) -> None:
        _write_quick_task("QD-000111", "done")
        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = []
        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.core.task_pr_lookup.list_prs", return_value=[]) as mock_list_prs,
        ):
            result = runner.invoke(task_app, ["sync"])
        assert result.exit_code == 0
        assert "No in-review or open tasks to reconcile." in result.output
        mock_list_prs.assert_not_called()

    def test_malformed_quick_task_frontmatter_is_skipped(self) -> None:
        bad = Path(".ydk") / "tasks" / "QD-bad000.md"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("---\nid: [unclosed\n---\n\nbody\n", encoding="utf-8")
        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = []
        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.core.task_pr_lookup.list_prs", return_value=[]),
        ):
            result = runner.invoke(task_app, ["sync"])
        assert result.exit_code == 0


class TestTaskSyncRollup:
    def test_sync_of_last_tasks_closes_story_and_epic(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root = tmp_path / ".ydk"
        tasks, stories, epics = LocalTaskRepository(root), LocalStoryRepository(root), LocalEpicRepository(root)
        epic = epics.create_epic(EpicCreate(title="Big epic")).id
        story = stories.create_story(StoryCreate(title="S", epic_id=epic)).id
        t1 = tasks.create_task(TaskCreate(title="a", story_id=story)).id
        t2 = tasks.create_task(TaskCreate(title="b", story_id=story)).id
        tasks.update_status(t1, "in-review")
        tasks.update_status(t2, "in-review")
        monkeypatch.setattr("ydk.cli.task_cmd._get_repo", lambda: tasks)
        monkeypatch.setattr("ydk.cli.task_cmd._get_story_repo", lambda: stories)
        monkeypatch.setattr("ydk.cli.task_cmd._get_epic_repo", lambda: epics)
        pr = {"number": 5, "state": "MERGED", "createdAt": "2026-01-01T00:00:00Z"}
        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("ydk.core.task_pr_lookup.list_prs", return_value=[pr]),
            patch("ydk.core.task_pr_lookup.find_task_pr", return_value=pr),
        ):
            result = runner.invoke(task_app, ["sync"])
        assert result.exit_code == 0, result.output
        assert f'Epic {epic} "Big epic" complete (2/2 tasks)' in result.output
        assert f"Next: ydk memory retrospective --epic {epic}" in result.output
        assert next(e.status for e in epics.list_epics(status="all") if e.id == epic) == "done"

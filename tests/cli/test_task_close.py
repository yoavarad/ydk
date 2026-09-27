"""Tests for the `task close` command and _find_task_pr helper."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from ydk.cli.task_cmd import _find_task_pr, task_app
from ydk.models.pm import EpicCreate, StoryCreate, TaskCreate
from ydk.repositories.local.epics import LocalEpicRepository
from ydk.repositories.local.stories import LocalStoryRepository
from ydk.repositories.local.tasks import LocalTaskRepository

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

_ANSI = re.compile(r"\[[0-9;]*m")


class TestFindTaskPr:
    def test_returns_none_when_pr_list_empty(self) -> None:
        fake_result = MagicMock(returncode=0, stdout="[]")
        with patch("subprocess.run", return_value=fake_result):
            pr = _find_task_pr("T-001")
        assert pr is None

    def test_returns_none_when_gh_call_fails(self) -> None:
        fake_result = MagicMock(returncode=1, stdout="", stderr="gh: command not found")
        with patch("subprocess.run", return_value=fake_result):
            pr = _find_task_pr("T-001")
        assert pr is None

    def test_returns_none_on_malformed_json(self) -> None:
        fake_result = MagicMock(returncode=0, stdout="not json")
        with patch("subprocess.run", return_value=fake_result):
            pr = _find_task_pr("T-001")
        assert pr is None

    def test_includes_limit_flag_in_gh_command(self) -> None:
        fake_result = MagicMock(returncode=0, stdout="[]")
        with patch("subprocess.run", return_value=fake_result) as mock_run:
            _find_task_pr("T-001")
        cmd = mock_run.call_args[0][0]
        assert "--limit" in cmd
        assert mock_run.call_args.kwargs.get("encoding") == "utf-8"

    def test_matches_branch_with_different_leading_type_segment(self) -> None:
        """Branches from other schemes (e.g. quickdev's chore/qd-... or docs/qd-...)
        should match on the last path segment, case-insensitively, independent
        of the leading type prefix.
        """
        prs = [
            {
                "number": 50,
                "url": "https://example.com/50",
                "state": "OPEN",
                "headRefName": "chore/qd-7583d5-fix-thing",
                "mergedAt": None,
                "createdAt": "2026-01-01T00:00:00Z",
            }
        ]
        fake_result = MagicMock(returncode=0, stdout=json.dumps(prs))
        with patch("subprocess.run", return_value=fake_result):
            pr = _find_task_pr("QD-7583d5")
        assert pr is not None
        assert pr["number"] == 50

    def test_matches_exact_branch_name(self) -> None:
        prs = [
            {
                "number": 42,
                "url": "https://example.com/42",
                "state": "OPEN",
                "headRefName": "task/T-001",
                "mergedAt": None,
                "createdAt": "2026-01-01T00:00:00Z",
            }
        ]
        fake_result = MagicMock(returncode=0, stdout=json.dumps(prs))
        with patch("subprocess.run", return_value=fake_result):
            pr = _find_task_pr("T-001")
        assert pr is not None
        assert pr["number"] == 42

    def test_matches_slugged_branch_name(self) -> None:
        prs = [
            {
                "number": 43,
                "url": "https://example.com/43",
                "state": "MERGED",
                "headRefName": "task/T-001-fix-thing",
                "mergedAt": "2026-01-02T00:00:00Z",
                "createdAt": "2026-01-01T00:00:00Z",
            }
        ]
        fake_result = MagicMock(returncode=0, stdout=json.dumps(prs))
        with patch("subprocess.run", return_value=fake_result):
            pr = _find_task_pr("T-001")
        assert pr is not None
        assert pr["number"] == 43

    def test_matches_task_prefix_case_insensitively(self) -> None:
        """task_id may be stored mixed-case (e.g. T-A1B2C3D4) while branches are
        always lowercased; matching must be case-insensitive."""
        prs = [
            {
                "number": 60,
                "url": "https://example.com/60",
                "state": "OPEN",
                "headRefName": "task/t-a1b2c3d4-fix-thing",
                "mergedAt": None,
                "createdAt": "2026-01-01T00:00:00Z",
            }
        ]
        fake_result = MagicMock(returncode=0, stdout=json.dumps(prs))
        with patch("subprocess.run", return_value=fake_result):
            pr = _find_task_pr("T-A1B2C3D4")
        assert pr is not None
        assert pr["number"] == 60

    def test_does_not_match_prefix_collision(self) -> None:
        """Querying T-001 must not match a PR on branch task/T-0010."""
        prs = [
            {
                "number": 44,
                "url": "https://example.com/44",
                "state": "OPEN",
                "headRefName": "task/T-0010",
                "mergedAt": None,
                "createdAt": "2026-01-01T00:00:00Z",
            }
        ]
        fake_result = MagicMock(returncode=0, stdout=json.dumps(prs))
        with patch("subprocess.run", return_value=fake_result):
            pr = _find_task_pr("T-001")
        assert pr is None

    def test_returns_most_recently_created_when_multiple_matches(self) -> None:
        prs = [
            {
                "number": 1,
                "url": "https://example.com/1",
                "state": "CLOSED",
                "headRefName": "task/T-001",
                "mergedAt": None,
                "createdAt": "2026-01-01T00:00:00Z",
            },
            {
                "number": 2,
                "url": "https://example.com/2",
                "state": "OPEN",
                "headRefName": "task/T-001-retry",
                "mergedAt": None,
                "createdAt": "2026-02-01T00:00:00Z",
            },
        ]
        fake_result = MagicMock(returncode=0, stdout=json.dumps(prs))
        with patch("subprocess.run", return_value=fake_result):
            pr = _find_task_pr("T-001")
        assert pr is not None
        assert pr["number"] == 2

    def test_ignores_unrelated_branches(self) -> None:
        prs = [
            {
                "number": 10,
                "url": "https://example.com/10",
                "state": "OPEN",
                "headRefName": "task/T-999",
                "mergedAt": None,
                "createdAt": "2026-01-01T00:00:00Z",
            },
            {
                "number": 11,
                "url": "https://example.com/11",
                "state": "OPEN",
                "headRefName": "main",
                "mergedAt": None,
                "createdAt": "2026-01-01T00:00:00Z",
            },
            {
                "number": 12,
                "url": "https://example.com/12",
                "state": "MERGED",
                "headRefName": "task/T-001",
                "mergedAt": "2026-01-02T00:00:00Z",
                "createdAt": "2026-01-01T12:00:00Z",
            },
        ]
        fake_result = MagicMock(returncode=0, stdout=json.dumps(prs))
        with patch("subprocess.run", return_value=fake_result):
            pr = _find_task_pr("T-001")
        assert pr is not None
        assert pr["number"] == 12


class TestCloseCommand:
    def test_no_pr_found_exits_1_and_does_not_touch_repo(self) -> None:
        with (
            patch("ydk.cli.task_cmd._find_task_pr", return_value=None),
            patch("ydk.cli.task_cmd._get_repo") as mock_get_repo,
        ):
            result = runner.invoke(task_app, ["close", "T-001"])
        assert result.exit_code == 1
        assert "No PR found for task" in result.output
        mock_get_repo.assert_not_called()

    def test_open_pr_reports_not_merged_and_does_not_update_status(self) -> None:
        pr = {"number": 42, "state": "OPEN"}
        with (
            patch("ydk.cli.task_cmd._find_task_pr", return_value=pr),
            patch("ydk.cli.task_cmd._get_repo") as mock_get_repo,
        ):
            result = runner.invoke(task_app, ["close", "T-001"])
        assert result.exit_code == 0
        assert "not merged" in result.output
        mock_get_repo.return_value.update_status.assert_not_called()

    def test_closed_unmerged_pr_reports_not_merged_and_does_not_update_status(self) -> None:
        pr = {"number": 42, "state": "CLOSED"}
        with (
            patch("ydk.cli.task_cmd._find_task_pr", return_value=pr),
            patch("ydk.cli.task_cmd._get_repo") as mock_get_repo,
        ):
            result = runner.invoke(task_app, ["close", "T-001"])
        assert result.exit_code == 0
        assert "not merged" in result.output
        mock_get_repo.return_value.update_status.assert_not_called()

    def test_merged_pr_updates_status_to_done(self) -> None:
        pr = {"number": 42, "state": "MERGED"}
        mock_repo = MagicMock()
        with (
            patch("ydk.cli.task_cmd._find_task_pr", return_value=pr),
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
        ):
            result = runner.invoke(task_app, ["close", "T-001"])
        assert result.exit_code == 0
        mock_repo.update_status.assert_called_once_with("T-001", "done")

    def test_merged_pr_updates_status_regardless_of_prior_task_status(self) -> None:
        """The close command never reads current task status (no get_task call) --
        it reconciles purely from PR merge state, even if the task is currently
        open/in-progress rather than in-review. get_task is deliberately left
        unstubbed here to prove it's never called.
        """
        pr = {"number": 42, "state": "MERGED"}
        mock_repo = MagicMock()
        with (
            patch("ydk.cli.task_cmd._find_task_pr", return_value=pr),
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
        ):
            result = runner.invoke(task_app, ["close", "T-001"])
        assert result.exit_code == 0
        mock_repo.update_status.assert_called_once_with("T-001", "done")
        mock_repo.get_task.assert_not_called()

    def test_update_status_failure_exits_1_without_traceback(self) -> None:
        pr = {"number": 42, "state": "MERGED"}
        mock_repo = MagicMock()
        mock_repo.update_status.side_effect = RuntimeError("gh issue close failed")
        with (
            patch("ydk.cli.task_cmd._find_task_pr", return_value=pr),
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
        ):
            result = runner.invoke(task_app, ["close", "T-001"])
        assert result.exit_code == 1
        assert "gh issue close failed" in result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)


@pytest.fixture
def local_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalTaskRepository:
    """Real LocalTaskRepository on tmp_path, wired into the CLI; gh PR lookup returns None."""
    repo = LocalTaskRepository(tmp_path / ".ydk")
    monkeypatch.setattr("ydk.cli.task_cmd._get_repo", lambda: repo)
    monkeypatch.setattr("ydk.cli.task_cmd._get_story_repo", lambda: LocalStoryRepository(tmp_path / ".ydk"))
    monkeypatch.setattr("ydk.cli.task_cmd._get_epic_repo", lambda: LocalEpicRepository(tmp_path / ".ydk"))
    monkeypatch.setattr("ydk.cli.task_cmd._find_task_pr", lambda _task_id: None)
    return repo


def _comment_text(repo: LocalTaskRepository, task_id: str) -> str:
    file_path = repo._tasks_dir / f"{task_id}.md"
    return file_path.read_text(encoding="utf-8")


def _manifest_status(repo: LocalTaskRepository, task_id: str) -> str:
    return str(repo._manifest.load()["tasks"][task_id]["status"])


class TestCloseWithoutPr:
    def _make_task(self, repo: LocalTaskRepository, title: str = "Task") -> str:
        return repo.create_task(TaskCreate(title=title, story_id="S-001")).id

    def test_delivered_by_existing_task_id_closes_and_records_ref(self, local_repo: LocalTaskRepository) -> None:
        target = self._make_task(local_repo, "Target")
        delivered = self._make_task(local_repo, "Deliverer")
        result = runner.invoke(task_app, ["close", target, "--delivered-by", delivered])
        assert result.exit_code == 0, result.output
        assert local_repo.get_task(target).status == "done"
        assert _manifest_status(local_repo, target) == "done"
        assert delivered in _comment_text(local_repo, target)

    def test_delivered_by_pr_url_closes_and_records_url(self, local_repo: LocalTaskRepository) -> None:
        target = self._make_task(local_repo)
        url = "https://github.com/acme/repo/pull/42"
        result = runner.invoke(task_app, ["close", target, "--delivered-by", url])
        assert result.exit_code == 0, result.output
        assert local_repo.get_task(target).status == "done"
        assert url in _comment_text(local_repo, target)

    def test_delivered_by_pr_number_closes_and_records_number(self, local_repo: LocalTaskRepository) -> None:
        target = self._make_task(local_repo)
        result = runner.invoke(task_app, ["close", target, "--delivered-by", "#42"])
        assert result.exit_code == 0, result.output
        assert local_repo.get_task(target).status == "done"
        assert "#42" in _comment_text(local_repo, target)

    def test_reason_closes_and_records_reason(self, local_repo: LocalTaskRepository) -> None:
        target = self._make_task(local_repo)
        result = runner.invoke(task_app, ["close", target, "--reason", "dup of X"])
        assert result.exit_code == 0, result.output
        assert local_repo.get_task(target).status == "done"
        assert _manifest_status(local_repo, target) == "done"
        assert "dup of X" in _comment_text(local_repo, target)

    def test_both_flags_record_both(self, local_repo: LocalTaskRepository) -> None:
        target = self._make_task(local_repo, "Target")
        delivered = self._make_task(local_repo, "Deliverer")
        result = runner.invoke(task_app, ["close", target, "--delivered-by", delivered, "--reason", "covered by it"])
        assert result.exit_code == 0, result.output
        assert local_repo.get_task(target).status == "done"
        text = _comment_text(local_repo, target)
        assert delivered in text
        assert "covered by it" in text

    def test_flags_skip_pr_lookup(self, local_repo: LocalTaskRepository, monkeypatch: pytest.MonkeyPatch) -> None:
        target = self._make_task(local_repo)

        def _boom(_task_id: str) -> None:
            raise AssertionError("PR lookup must be skipped when flags are given")

        monkeypatch.setattr("ydk.cli.task_cmd._find_task_pr", _boom)
        result = runner.invoke(task_app, ["close", target, "--reason", "not needed"])
        assert result.exit_code == 0, result.output

    def test_no_pr_and_no_flags_exits_1_with_hint(self, local_repo: LocalTaskRepository) -> None:
        target = self._make_task(local_repo)
        result = runner.invoke(task_app, ["close", target])
        assert result.exit_code == 1
        assert "--delivered-by" in result.output
        assert "--reason" in result.output
        assert local_repo.get_task(target).status == "open"

    def test_unknown_delivered_by_task_id_exits_1_without_side_effects(self, local_repo: LocalTaskRepository) -> None:
        target = self._make_task(local_repo)
        before = _comment_text(local_repo, target)
        result = runner.invoke(task_app, ["close", target, "--delivered-by", "T-999"])
        assert result.exit_code == 1
        assert local_repo.get_task(target).status == "open"
        assert _manifest_status(local_repo, target) == "open"
        assert _comment_text(local_repo, target) == before

    def test_failed_comment_aborts_close(
        self, local_repo: LocalTaskRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = self._make_task(local_repo)

        def _fail(_task_id: str, _comment: str) -> None:
            raise RuntimeError("comment failed")

        monkeypatch.setattr(local_repo, "add_comment", _fail)
        result = runner.invoke(task_app, ["close", target, "--reason", "dup"])
        assert result.exit_code == 1
        assert "comment failed" in result.output
        assert local_repo.get_task(target).status == "open"


class TestClosePrPathsUnchangedWithRealRepo:
    def test_merged_pr_sets_done_and_writes_no_comment(
        self, local_repo: LocalTaskRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = local_repo.create_task(TaskCreate(title="T", story_id="S-001")).id
        monkeypatch.setattr("ydk.cli.task_cmd._find_task_pr", lambda _id: {"number": 42, "state": "MERGED"})
        before = _comment_text(local_repo, target)
        result = runner.invoke(task_app, ["close", target])
        assert result.exit_code == 0, result.output
        assert local_repo.get_task(target).status == "done"
        assert "PR #42 merged" in result.output
        assert "###" not in _comment_text(local_repo, target).replace(before, "")

    def test_open_pr_leaves_status_unchanged(
        self, local_repo: LocalTaskRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = local_repo.create_task(TaskCreate(title="T", story_id="S-001")).id
        monkeypatch.setattr("ydk.cli.task_cmd._find_task_pr", lambda _id: {"number": 7, "state": "OPEN"})
        result = runner.invoke(task_app, ["close", target])
        assert result.exit_code == 0
        assert "not merged" in result.output
        assert local_repo.get_task(target).status == "open"


class TestCloseRollsUpStoryAndEpic:
    """Closing the last task of an epic closes its story and epic and prints the next step."""

    @staticmethod
    def _seed(tmp_path: Path, repo: LocalTaskRepository) -> tuple[str, str, str, str]:
        epic = LocalEpicRepository(tmp_path / ".ydk").create_epic(EpicCreate(title="Big epic")).id
        story = LocalStoryRepository(tmp_path / ".ydk").create_story(StoryCreate(title="S", epic_id=epic)).id
        first = repo.create_task(TaskCreate(title="a", story_id=story)).id
        last = repo.create_task(TaskCreate(title="b", story_id=story)).id
        return epic, story, first, last

    @staticmethod
    def _epic_status(tmp_path: Path, epic: str) -> str:
        return next(e.status for e in LocalEpicRepository(tmp_path / ".ydk").list_epics(status="all") if e.id == epic)

    def test_merged_pr_close_of_last_task_closes_epic(
        self, tmp_path: Path, local_repo: LocalTaskRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        epic, _story, first, last = self._seed(tmp_path, local_repo)
        monkeypatch.setattr("ydk.cli.task_cmd._find_task_pr", lambda _id: {"number": 1, "state": "MERGED"})
        result = runner.invoke(task_app, ["close", first])
        assert result.exit_code == 0, result.output
        assert "Epic" not in result.output
        assert self._epic_status(tmp_path, epic) == "open"

        result = runner.invoke(task_app, ["close", last])
        assert result.exit_code == 0, result.output
        assert f'Epic {epic} "Big epic" complete (2/2 tasks)' in result.output
        assert f"Next: ydk memory retrospective --epic {epic}" in result.output
        assert self._epic_status(tmp_path, epic) == "done"

    def test_delivered_by_close_of_last_task_closes_epic(self, tmp_path: Path, local_repo: LocalTaskRepository) -> None:
        epic, _story, first, last = self._seed(tmp_path, local_repo)
        runner.invoke(task_app, ["close", first, "--reason", "dup"])
        result = runner.invoke(task_app, ["close", last, "--delivered-by", first])
        assert result.exit_code == 0, result.output
        assert f'Epic {epic} "Big epic" complete' in result.output
        assert self._epic_status(tmp_path, epic) == "done"

    def test_reason_close_of_task_without_story_prints_no_rollup(self, local_repo: LocalTaskRepository) -> None:
        orphan = local_repo.create_task(TaskCreate(title="orphan")).id
        result = runner.invoke(task_app, ["close", orphan, "--reason", "n/a"])
        assert result.exit_code == 0, result.output
        assert "complete" not in result.output


class TestCloseHelp:
    @staticmethod
    def _help() -> str:
        result = runner.invoke(task_app, ["close", "--help"], env={"COLUMNS": "200", "NO_COLOR": "1"})
        assert result.exit_code == 0
        # Typer forces ANSI styling on GitHub Actions (GITHUB_ACTIONS) even when NO_COLOR is set.
        return " ".join(_ANSI.sub("", result.output).split())

    def test_help_explains_when_to_run_and_status_not_auto_updated(self) -> None:
        out = self._help()
        assert "AFTER the task's PR is merged" in out
        assert "does NOT auto-update" in out

    def test_help_mentions_recovery_of_stuck_task(self) -> None:
        out = self._help()
        assert "stuck" in out
        assert "recover" in out.lower()

    def test_help_explains_merge_check_and_noop_when_unmerged(self) -> None:
        out = self._help()
        assert "gh" in out
        assert "merge" in out
        assert "nothing" in out.lower()

    def test_help_documents_no_pr_flags(self) -> None:
        out = self._help()
        assert "--delivered-by" in out
        assert "--reason" in out
        assert "audit comment" in out

    def test_help_points_to_sync_for_bulk(self) -> None:
        assert "ydk task sync" in self._help()

    def test_help_includes_usage_example(self) -> None:
        out = self._help()
        assert "ydk task close T-a1b2c3d4" in out

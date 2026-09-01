"""Tests for the `task close` command and _find_task_pr helper."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ydk.cli.task_cmd import _find_task_pr, task_app

runner = CliRunner()


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

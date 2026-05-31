"""Tests for the review-comments command and _fetch_review_comments helper."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from odk.cli.task_cmd import _fetch_review_comments, task_app

runner = CliRunner()


class TestFetchReviewComments:
    def test_returns_empty_when_no_pr_found(self) -> None:
        fake_result = MagicMock(returncode=1, stdout="", stderr="no PR found")
        with patch("subprocess.run", return_value=fake_result):
            comments = _fetch_review_comments("T-999")
        assert comments == []

    def test_returns_empty_when_pr_list_empty(self) -> None:
        fake_result = MagicMock(returncode=0, stdout="[]")
        with patch("subprocess.run", return_value=fake_result):
            comments = _fetch_review_comments("T-999")
        assert comments == []

    def test_parses_review_comments(self) -> None:
        pr_list_result = MagicMock(returncode=0, stdout=json.dumps([{"number": 42, "url": "https://example.com"}]))
        api_result = MagicMock(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "path": "src/app/config.py",
                        "line": 12,
                        "body": "Consider using SecretStr",
                        "user": {"login": "oz"},
                    },
                    {
                        "path": "src/app/config.py",
                        "line": 45,
                        "body": "Missing default docs",
                        "user": {"login": "oz"},
                    },
                ]
            ),
        )
        threads_result = MagicMock(returncode=0, stdout=json.dumps({"reviewThreads": []}))

        call_count = 0

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return pr_list_result
            if call_count == 2:
                return api_result
            return threads_result

        with patch("subprocess.run", side_effect=mock_run):
            comments = _fetch_review_comments("T-001")

        assert len(comments) == 2
        assert comments[0]["path"] == "src/app/config.py"
        assert comments[0]["line"] == 12
        assert comments[0]["author"] == "oz"

    def test_marks_resolved_threads(self) -> None:
        pr_list_result = MagicMock(returncode=0, stdout=json.dumps([{"number": 42, "url": "https://example.com"}]))
        api_result = MagicMock(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "path": "src/foo.py",
                        "line": 1,
                        "body": "Fix this",
                        "user": {"login": "reviewer"},
                    },
                ]
            ),
        )
        threads_result = MagicMock(
            returncode=0,
            stdout=json.dumps(
                {
                    "reviewThreads": [
                        {
                            "isResolved": True,
                            "comments": [{"body": "Fix this"}],
                        }
                    ]
                }
            ),
        )

        call_count = 0

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return pr_list_result
            if call_count == 2:
                return api_result
            return threads_result

        with patch("subprocess.run", side_effect=mock_run):
            comments = _fetch_review_comments("T-001")

        assert len(comments) == 1
        assert comments[0]["resolved"] is True


class TestReviewCommentsCommand:
    def test_no_comments_output(self) -> None:
        with patch("odk.cli.task_cmd._fetch_review_comments", return_value=[]):
            result = runner.invoke(task_app, ["review-comments", "T-999"])
        assert result.exit_code == 0
        assert "No review comments found" in result.output

    def test_displays_unresolved_comments(self) -> None:
        mock_comments = [
            {"path": "src/config.py", "line": 12, "body": "Use SecretStr", "author": "oz", "resolved": False},
            {"path": "src/config.py", "line": 45, "body": "Add docs", "author": "oz", "resolved": False},
        ]
        with patch("odk.cli.task_cmd._fetch_review_comments", return_value=mock_comments):
            result = runner.invoke(task_app, ["review-comments", "T-001"])
        assert result.exit_code == 0
        assert "2 unresolved" in result.output
        assert "src/config.py:12" in result.output
        assert "Use SecretStr" in result.output

    def test_shows_resolved_count(self) -> None:
        mock_comments = [
            {"path": "src/a.py", "line": 1, "body": "Fix", "author": "oz", "resolved": True},
            {"path": "src/b.py", "line": 2, "body": "Fix too", "author": "oz", "resolved": False},
        ]
        with patch("odk.cli.task_cmd._fetch_review_comments", return_value=mock_comments):
            result = runner.invoke(task_app, ["review-comments", "T-001"])
        assert "1 unresolved" in result.output
        assert "1 resolved" in result.output

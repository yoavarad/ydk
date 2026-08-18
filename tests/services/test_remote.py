"""Tests for GitHubRemoteService — all mocked (no real GitHub calls)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from ydk.services.remote import GitHubRemoteService


class TestCreateIssue:
    def test_constructs_correct_command(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=0, stdout="https://github.com/org/repo/issues/42\n")
        with patch("subprocess.run", return_value=fake) as mock_run:
            url = svc.create_issue("Bug title", "Bug body", ["bug", "p1"])
        assert url == "https://github.com/org/repo/issues/42"
        cmd = mock_run.call_args[0][0]
        assert "gh" in cmd
        assert "issue" in cmd
        assert "create" in cmd
        assert "--title" in cmd
        assert "Bug title" in cmd
        assert "--label" in cmd

    def test_with_milestone(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=0, stdout="https://github.com/org/repo/issues/43\n")
        with patch("subprocess.run", return_value=fake) as mock_run:
            svc.create_issue("Title", "Body", ["feat"], milestone="v1.0")
        cmd = mock_run.call_args[0][0]
        assert "--milestone" in cmd
        assert "v1.0" in cmd

    def test_raises_on_failure(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=1, stdout="", stderr="auth error")
        with patch("subprocess.run", return_value=fake), pytest.raises(RuntimeError):
            svc.create_issue("Title", "Body", ["bug"])


class TestListIssues:
    def test_parses_json_output(self) -> None:
        svc = GitHubRemoteService()
        issues = [
            {"number": 1, "title": "First", "state": "OPEN", "labels": [{"name": "bug"}], "body": "desc"},
            {"number": 2, "title": "Second", "state": "OPEN", "labels": [], "body": ""},
        ]
        fake = MagicMock(returncode=0, stdout=json.dumps(issues))
        with patch("subprocess.run", return_value=fake):
            result = svc.list_issues()
        assert len(result) == 2
        assert result[0]["number"] == 1

    def test_with_filters(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=0, stdout="[]")
        with patch("subprocess.run", return_value=fake) as mock_run:
            svc.list_issues(milestone="v1.0", labels=["bug"], state="closed")
        cmd = mock_run.call_args[0][0]
        assert "--milestone" in cmd
        assert "--label" in cmd
        assert "--state" in cmd
        assert "closed" in cmd

    def test_returns_empty_on_failure(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=1, stdout="", stderr="error")
        with patch("subprocess.run", return_value=fake):
            result = svc.list_issues()
        assert result == []


class TestAddLabel:
    def test_calls_correct_command(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=0, stdout="")
        with patch("subprocess.run", return_value=fake) as mock_run:
            svc.add_label(42, "priority/high")
        cmd = mock_run.call_args[0][0]
        assert "gh" in cmd
        assert "issue" in cmd
        assert "edit" in cmd
        assert "42" in [str(c) for c in cmd]
        assert "--add-label" in cmd
        assert "priority/high" in cmd

    def test_raises_on_failure(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=1, stdout="", stderr="not found")
        with patch("subprocess.run", return_value=fake), pytest.raises(RuntimeError):
            svc.add_label(999, "bug")


class TestAddComment:
    def test_calls_correct_command(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=0, stdout="")
        with patch("subprocess.run", return_value=fake) as mock_run:
            svc.add_comment(42, "LGTM!")
        cmd = mock_run.call_args[0][0]
        assert "gh" in cmd
        assert "issue" in cmd
        assert "comment" in cmd
        assert "42" in [str(c) for c in cmd]
        assert "--body" in cmd
        assert "LGTM!" in cmd

    def test_raises_on_failure(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=1, stdout="", stderr="error")
        with patch("subprocess.run", return_value=fake), pytest.raises(RuntimeError):
            svc.add_comment(42, "comment")

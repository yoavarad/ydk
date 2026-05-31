"""Tests for odk.core.watch — WatchManager session tracking, polling, and plist generation."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import yaml

from odk.core.watch import WatchManager


@pytest.fixture
def project_root(tmp_path):
    """Create a temp project root with .odk directory."""
    odk_dir = tmp_path / ".odk"
    odk_dir.mkdir()
    return tmp_path


@pytest.fixture
def mgr(project_root):
    return WatchManager(project_root)


# -- Session tracking --


class TestRecordSession:
    def test_creates_sessions_file(self, mgr, project_root):
        mgr.record_session("891", "abc123", "task/891-settings")

        sessions_file = project_root / ".odk" / "sessions.yaml"
        assert sessions_file.is_file()

        data = yaml.safe_load(sessions_file.read_text())
        assert "891" in data["sessions"]
        assert data["sessions"]["891"]["session_id"] == "abc123"
        assert data["sessions"]["891"]["branch"] == "task/891-settings"
        assert data["sessions"]["891"]["status"] == "open"
        assert data["sessions"]["891"]["last_polled"] is None

    def test_overwrites_existing_session(self, mgr):
        mgr.record_session("891", "abc123", "task/891-v1")
        mgr.record_session("891", "def456", "task/891-v2")

        sessions = mgr.get_active_sessions()
        assert sessions["891"]["session_id"] == "def456"
        assert sessions["891"]["branch"] == "task/891-v2"

    def test_multiple_sessions(self, mgr):
        mgr.record_session("891", "abc123", "task/891")
        mgr.record_session("892", "def456", "task/892")

        sessions = mgr.get_active_sessions()
        assert len(sessions) == 2


class TestRecordPr:
    def test_records_pr_number(self, mgr):
        mgr.record_session("891", "abc123", "task/891")
        mgr.record_pr("891", 914)

        sessions = mgr.get_active_sessions()
        assert sessions["891"]["pr_number"] == 914

    def test_ignores_unknown_task(self, mgr):
        mgr.record_pr("999", 100)  # no session recorded — should not crash
        sessions = mgr.get_active_sessions()
        assert "999" not in sessions


class TestMarkDone:
    def test_marks_session_done(self, mgr):
        mgr.record_session("891", "abc123", "task/891")
        mgr.mark_done("891")

        sessions = mgr.get_active_sessions()
        assert sessions["891"]["status"] == "done"


# -- Polling --


class TestPoll:
    def test_no_sessions_returns_empty(self, mgr):
        results = mgr.poll()
        assert results == []

    def test_skips_sessions_without_pr(self, mgr):
        mgr.record_session("891", "abc123", "task/891")
        # No PR recorded
        results = mgr.poll()
        assert results == []

    def test_skips_done_sessions(self, mgr):
        mgr.record_session("891", "abc123", "task/891")
        mgr.record_pr("891", 914)
        mgr.mark_done("891")

        results = mgr.poll()
        assert results == []

    @patch("odk.core.watch.subprocess.run")
    def test_detects_new_comments(self, mock_run, mgr):
        mgr.record_session("891", "abc123", "task/891")
        mgr.record_pr("891", 914)

        comments_response = json.dumps(
            [
                {
                    "path": "src/main.py",
                    "line": 42,
                    "body": "Please add a docstring here",
                    "user": {"login": "reviewer"},
                    "created_at": "2026-05-01T10:00:00Z",
                }
            ]
        )
        reviews_response = json.dumps([])

        def side_effect(cmd, **kwargs):
            mock = MagicMock()
            mock.returncode = 0
            if "pulls" in cmd[2] and "comments" in cmd[2]:
                mock.stdout = comments_response
            elif "issues" in cmd[2] and "comments" in cmd[2]:
                mock.stdout = json.dumps([])
            elif "reactions" in cmd[2]:
                mock.stdout = ""
            else:
                mock.stdout = reviews_response
            return mock

        mock_run.side_effect = side_effect

        results = mgr.poll()
        assert len(results) == 1
        assert results[0]["task_id"] == "891"
        assert results[0]["session_id"] == "abc123"
        assert results[0]["pr_number"] == 914
        assert len(results[0]["comments"]) == 1
        assert results[0]["comments"][0]["path"] == "src/main.py"

    @patch("odk.core.watch.subprocess.run")
    def test_filters_old_comments(self, mock_run, mgr):
        mgr.record_session("891", "abc123", "task/891")
        mgr.record_pr("891", 914)

        # Set last_polled to after the comment
        sessions = mgr._load_sessions()
        sessions["891"]["last_polled"] = "2026-05-02T00:00:00Z"
        mgr._save_sessions(sessions)

        comments_response = json.dumps(
            [
                {
                    "path": "src/main.py",
                    "line": 42,
                    "body": "Old comment",
                    "user": {"login": "reviewer"},
                    "created_at": "2026-05-01T10:00:00Z",  # Before last_polled
                }
            ]
        )
        reviews_response = json.dumps([])

        def side_effect(cmd, **kwargs):
            mock = MagicMock()
            mock.returncode = 0
            if "pulls" in cmd[2] and "comments" in cmd[2]:
                mock.stdout = comments_response
            elif "issues" in cmd[2] and "comments" in cmd[2]:
                mock.stdout = json.dumps([])
            elif "reactions" in cmd[2]:
                mock.stdout = ""
            else:
                mock.stdout = reviews_response
            return mock

        mock_run.side_effect = side_effect

        results = mgr.poll()
        assert len(results) == 0

    @patch("odk.core.watch.subprocess.run")
    def test_updates_last_polled(self, mock_run, mgr):
        mgr.record_session("891", "abc123", "task/891")
        mgr.record_pr("891", 914)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "[]"
        mock_run.return_value = mock_result

        mgr.poll()

        sessions = mgr.get_active_sessions()
        assert sessions["891"]["last_polled"] is not None

    @patch("odk.core.watch.subprocess.run")
    def test_includes_review_bodies(self, mock_run, mgr):
        mgr.record_session("891", "abc123", "task/891")
        mgr.record_pr("891", 914)

        comments_response = json.dumps([])
        reviews_response = json.dumps(
            [
                {
                    "body": "Please fix the formatting",
                    "user": {"login": "lead"},
                    "submitted_at": "2026-05-01T12:00:00Z",
                }
            ]
        )

        def side_effect(cmd, **kwargs):
            mock = MagicMock()
            mock.returncode = 0
            if "pulls" in cmd[2] and "comments" in cmd[2]:
                mock.stdout = comments_response
            elif "issues" in cmd[2] and "comments" in cmd[2]:
                mock.stdout = json.dumps([])
            elif "reactions" in cmd[2]:
                mock.stdout = ""
            else:
                mock.stdout = reviews_response
            return mock

        mock_run.side_effect = side_effect

        results = mgr.poll()
        assert len(results) == 1
        assert results[0]["comments"][0]["path"] == "(review)"
        assert "formatting" in results[0]["comments"][0]["body"]


# -- Lock file --


class TestLock:
    def test_acquire_and_release(self, mgr):
        assert mgr.acquire_lock() is True
        mgr.release_lock()

    def test_double_acquire_fails(self, mgr, project_root):
        mgr.acquire_lock()

        # Second manager trying to acquire the same lock
        mgr2 = WatchManager(project_root)
        assert mgr2.acquire_lock() is False

        mgr.release_lock()

    def test_acquire_after_release(self, mgr, project_root):
        mgr.acquire_lock()
        mgr.release_lock()

        mgr2 = WatchManager(project_root)
        assert mgr2.acquire_lock() is True
        mgr2.release_lock()


# -- Plist generation --


class TestPlist:
    def test_generates_valid_plist(self, mgr, project_root):
        plist = mgr.generate_plist()
        assert "com.odk.watch." in plist
        assert str(project_root) in plist
        assert "<integer>30</integer>" in plist
        assert "watch-stdout.log" in plist
        assert "watch-stderr.log" in plist

    def test_custom_label(self, mgr):
        plist = mgr.generate_plist(label="com.test.custom")
        assert "com.test.custom" in plist

    def test_plist_path(self, mgr, project_root):
        path = mgr.plist_path()
        assert "LaunchAgents" in str(path)
        assert project_root.name in str(path)

    def test_creates_log_directory(self, mgr, project_root):
        mgr.generate_plist()
        assert (project_root / ".odk" / "logs").is_dir()


# -- Agent triggering --


class TestTriggerAgent:
    @patch("odk.core.watch.subprocess.Popen")
    def test_constructs_correct_command(self, mock_popen, mgr):
        mgr.trigger_agent("session-abc", "/path/to/project", "Fix the tests")

        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd == ["claude", "--resume", "session-abc", "--dangerously-skip-permissions", "-p", "Fix the tests"]
        assert mock_popen.call_args[1]["cwd"] == "/path/to/project"


# -- Last poll time --


class TestLastPollTime:
    def test_no_sessions(self, mgr):
        assert mgr.last_poll_time() is None

    def test_no_polled_sessions(self, mgr):
        mgr.record_session("891", "abc", "task/891")
        assert mgr.last_poll_time() is None

    def test_returns_most_recent(self, mgr):
        mgr.record_session("891", "abc", "task/891")
        mgr.record_session("892", "def", "task/892")

        sessions = mgr._load_sessions()
        sessions["891"]["last_polled"] = "2026-05-01T10:00:00Z"
        sessions["892"]["last_polled"] = "2026-05-01T12:00:00Z"
        mgr._save_sessions(sessions)

        assert mgr.last_poll_time() == "2026-05-01T12:00:00Z"

"""Tests for odk watch CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from odk.cli.main import app

runner = CliRunner()


@patch("odk.cli.watch_cmd.Path")
def test_watch_status_no_install(mock_path):
    """Status shows NOT INSTALLED when plist missing."""
    # We need to mock at a deeper level for real isolation
    with (
        patch("odk.core.watch.WatchManager.plist_path") as mock_plist_path,
        patch("odk.core.watch.WatchManager.last_poll_time", return_value=None),
        patch("odk.core.watch.WatchManager.get_active_sessions", return_value={}),
    ):
        mock_plist_path.return_value = Path("/nonexistent/path.plist")
        result = runner.invoke(app, ["watch", "status"])
        assert result.exit_code == 0
        assert "NOT INSTALLED" in result.output


@patch("odk.core.watch.WatchManager.plist_path")
@patch("odk.core.watch.WatchManager.last_poll_time", return_value="2026-05-01T12:00:00Z")
@patch("odk.core.watch.WatchManager.get_active_sessions")
def test_watch_status_with_sessions(mock_sessions, mock_last, mock_plist):
    mock_plist.return_value = Path("/nonexistent/path.plist")
    mock_sessions.return_value = {
        "891": {
            "session_id": "abc123-def456-ghi789",
            "pr_number": 914,
            "status": "open",
        }
    }
    result = runner.invoke(app, ["watch", "status"])
    assert result.exit_code == 0
    assert "2026-05-01T12:00:00Z" in result.output
    assert "891" in result.output
    assert "914" in result.output


@patch("odk.core.watch.WatchManager.acquire_lock", return_value=False)
def test_poll_skips_when_locked(mock_lock):
    result = runner.invoke(app, ["watch", "poll"])
    assert result.exit_code == 0
    assert "already running" in result.output


@patch("odk.core.watch.WatchManager.release_lock")
@patch("odk.core.watch.WatchManager.acquire_lock", return_value=True)
@patch("odk.core.watch.WatchManager.poll", return_value=[])
def test_poll_no_comments(mock_poll, mock_lock, mock_release):
    result = runner.invoke(app, ["watch", "poll"])
    assert result.exit_code == 0
    assert "No new review comments" in result.output


@patch("odk.core.watch.WatchManager.release_lock")
@patch("odk.core.watch.WatchManager.acquire_lock", return_value=True)
@patch("odk.core.watch.WatchManager.trigger_agent")
@patch("odk.core.watch.WatchManager.poll")
def test_poll_triggers_agent(mock_poll, mock_trigger, mock_lock, mock_release):
    mock_poll.return_value = [
        {
            "task_id": "891",
            "session_id": "abc123",
            "pr_number": 914,
            "comments": [
                {"path": "src/main.py", "line": 42, "body": "Fix this"},
            ],
        }
    ]

    result = runner.invoke(app, ["watch", "poll"])
    assert result.exit_code == 0
    assert "Triggered session abc123" in result.output
    mock_trigger.assert_called_once()


@patch("odk.core.watch.WatchManager.plist_path")
def test_uninstall_when_not_installed(mock_plist):
    mock_plist.return_value = Path("/nonexistent/path.plist")
    result = runner.invoke(app, ["watch", "uninstall"])
    assert result.exit_code == 1
    assert "No watcher installed" in result.output

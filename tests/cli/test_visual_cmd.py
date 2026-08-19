"""Tests for ydk visual commands."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ydk.cli import app
from ydk.models.visual import SessionStatus, VisualSession

runner = CliRunner()


def _fake_session(tmp_path, session_id="abc123", port=5173, pid=9999, status=SessionStatus.running):
    content_dir = tmp_path / ".ydk" / "visual" / session_id / "content"
    state_dir = tmp_path / ".ydk" / "visual" / session_id / "state"
    content_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    session = VisualSession(
        id=session_id,
        port=port,
        url=f"http://localhost:{port}",
        content_dir=str(content_dir),
        state_dir=str(state_dir),
        pid=pid,
        status=status,
    )
    (state_dir / "server-info.json").write_text(json.dumps(session.model_dump(), indent=2))
    return session


def test_visual_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("ydk.core.visual.subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc
        result = runner.invoke(app, ["visual", "start", "--project-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Session started" in result.output


def test_visual_stop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session = _fake_session(tmp_path)
    if os.name != "nt":
        with patch("os.killpg"), patch("os.getpgid", return_value=9999):
            result = runner.invoke(app, ["visual", "stop", session.id, "--project-dir", str(tmp_path)])
    else:
        with patch("os.kill"):
            result = runner.invoke(app, ["visual", "stop", session.id, "--project-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "stopped" in result.output


def test_visual_stop_nonexistent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["visual", "stop", "nonexistent", "--project-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_visual_push(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session = _fake_session(tmp_path)
    result = runner.invoke(
        app,
        [
            "visual",
            "push",
            "<h1>Hello</h1>",
            "--session-id",
            session.id,
            "--project-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0
    assert "pushed" in result.output
    assert (Path(session.content_dir) / "index.html").read_text() == "<h1>Hello</h1>"


def test_visual_push_no_sessions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["visual", "push", "<h1>Hi</h1>", "--project-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "No active sessions" in result.output


def test_visual_feedback_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _fake_session(tmp_path)
    result = runner.invoke(
        app,
        [
            "visual",
            "feedback",
            "--session-id",
            "abc123",
            "--project-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0
    assert "No feedback" in result.output


def test_visual_feedback_with_events(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session = _fake_session(tmp_path)
    event = {"type": "selection", "choice": "a", "choiceText": "Option A", "timestamp": 1700000000}
    (Path(session.state_dir) / "feedback.jsonl").write_text(json.dumps(event) + "\n")

    result = runner.invoke(
        app,
        [
            "visual",
            "feedback",
            "--session-id",
            session.id,
            "--project-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0
    assert "Option A" in result.output


def test_visual_list_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["visual", "list", "--project-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No visual sessions" in result.output


def test_visual_list_shows_sessions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _fake_session(tmp_path, session_id="sess1", port=5173)
    _fake_session(tmp_path, session_id="sess2", port=5174)
    result = runner.invoke(app, ["visual", "list", "--project-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "sess1" in result.output
    assert "sess2" in result.output


def test_visual_screenshot_no_sessions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["visual", "screenshot", "--project-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "No active sessions" in result.output

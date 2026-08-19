"""Tests for the visual companion engine."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ydk.core.visual import VisualEngine
from ydk.models.visual import (
    AnchorInfo,
    BoundingRect,
    ComponentInfo,
    ElementAnnotationEvent,
    RectangleAnnotationEvent,
    RectPct,
    SelectionEvent,
    SessionStatus,
    ViewportInfo,
    VisualSession,
)

# --- Model validation ---


class TestModels:
    def test_visual_session_rejects_extra_fields(self):
        with pytest.raises(Exception, match="extra"):
            VisualSession(
                id="abc",
                port=3000,
                url="http://localhost:3000",
                content_dir="/tmp/c",
                state_dir="/tmp/s",
                unknown_field="bad",
            )

    def test_bounding_rect_round_trip(self):
        br = BoundingRect(x=10, y=20, width=100, height=50)
        assert br.model_dump() == {"x": 10, "y": 20, "width": 100, "height": 50}

    def test_viewport_info_round_trip(self):
        v = ViewportInfo(scrollX=0, scrollY=100, width=1440, height=900, devicePixelRatio=2)
        assert v.width == 1440

    def test_rect_pct_round_trip(self):
        r = RectPct(xPct=0.1, yPct=0.2, wPct=0.8, hPct=0.5)
        assert r.xPct == 0.1

    def test_anchor_info_optional_fields(self):
        a = AnchorInfo(cssSelector="div.test")
        assert a.xpath is None
        assert a.elementId is None

    def test_component_info(self):
        c = ComponentInfo(name="Button", path=["App", "Header", "Button"], library="shadcn")
        assert c.name == "Button"
        assert c.library == "shadcn"

    def test_selection_event(self):
        e = SelectionEvent(type="selection", choice="a", choiceText="Option A", timestamp=1700000000)
        assert e.type == "selection"
        assert e.choice == "a"

    def test_element_annotation_event(self):
        e = ElementAnnotationEvent(
            type="element_annotation",
            id="ann-123",
            comment="Make this bigger",
            anchor=AnchorInfo(cssSelector="button.cta", elementTag="BUTTON"),
            timestamp=1700000000,
        )
        assert e.comment == "Make this bigger"
        assert e.anchor.elementTag == "BUTTON"

    def test_rectangle_annotation_event(self):
        e = RectangleAnnotationEvent(
            type="rectangle_annotation",
            id="ann-456",
            comment="More whitespace here",
            rect=RectPct(xPct=0.05, yPct=0.1, wPct=0.9, hPct=0.35),
            timestamp=1700000000,
        )
        assert e.rect.wPct == 0.9

    def test_session_status_enum(self):
        assert SessionStatus.running.value == "running"
        assert SessionStatus.stopped.value == "stopped"


# --- Engine session lifecycle ---


class TestVisualEngineSessionLifecycle:
    def test_start_session_creates_dirs(self, tmp_path):
        engine = VisualEngine(project_dir=tmp_path)
        with patch("ydk.core.visual.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc
            session = engine.start_session()

        assert session.status == SessionStatus.running
        assert session.pid == 12345
        assert Path(session.content_dir).is_dir()
        assert Path(session.state_dir).is_dir()
        assert (Path(session.content_dir) / "index.html").exists()

    def test_get_session_returns_session(self, tmp_path):
        engine = VisualEngine(project_dir=tmp_path)
        with patch("ydk.core.visual.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc
            session = engine.start_session()

        retrieved = engine.get_session(session.id)
        assert retrieved is not None
        assert retrieved.id == session.id
        assert retrieved.port == session.port

    def test_get_session_returns_none_for_unknown(self, tmp_path):
        engine = VisualEngine(project_dir=tmp_path)
        assert engine.get_session("nonexistent") is None

    def test_list_sessions_empty(self, tmp_path):
        engine = VisualEngine(project_dir=tmp_path)
        assert engine.list_sessions() == []

    def test_list_sessions_finds_created(self, tmp_path):
        engine = VisualEngine(project_dir=tmp_path)
        with patch("ydk.core.visual.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 111
            mock_popen.return_value = mock_proc
            s1 = engine.start_session()
            mock_proc.pid = 222
            s2 = engine.start_session()

        sessions = engine.list_sessions()
        ids = {s.id for s in sessions}
        assert s1.id in ids
        assert s2.id in ids

    def test_stop_session_writes_sentinel(self, tmp_path):
        engine = VisualEngine(project_dir=tmp_path)
        with patch("ydk.core.visual.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc
            session = engine.start_session()

        if os.name != "nt":
            with patch("os.killpg"), patch("os.getpgid", return_value=12345):
                engine.stop_session(session.id)
        else:
            with patch("os.kill"):
                engine.stop_session(session.id)

        sentinel = Path(session.state_dir) / "server-stopped"
        assert sentinel.exists()

        updated = engine.get_session(session.id)
        assert updated is not None
        assert updated.status == SessionStatus.stopped

    def test_stop_nonexistent_session_raises(self, tmp_path):
        engine = VisualEngine(project_dir=tmp_path)
        with pytest.raises(ValueError, match="not found"):
            engine.stop_session("nonexistent")


# --- Content pushing ---


class TestPushContent:
    def test_push_content_creates_file(self, tmp_path):
        engine = VisualEngine(project_dir=tmp_path)
        with patch("ydk.core.visual.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 123
            mock_popen.return_value = mock_proc
            session = engine.start_session()

        path = engine.push_content(session.id, "<h1>Hello</h1>", "page.html")
        assert path.exists()
        assert path.read_text() == "<h1>Hello</h1>"
        assert path.name == "page.html"

    def test_push_content_overwrites_existing(self, tmp_path):
        engine = VisualEngine(project_dir=tmp_path)
        with patch("ydk.core.visual.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 123
            mock_popen.return_value = mock_proc
            session = engine.start_session()

        engine.push_content(session.id, "first", "index.html")
        engine.push_content(session.id, "second", "index.html")
        content_path = Path(session.content_dir) / "index.html"
        assert content_path.read_text() == "second"

    def test_push_content_nonexistent_session_raises(self, tmp_path):
        engine = VisualEngine(project_dir=tmp_path)
        with pytest.raises(ValueError, match="not found"):
            engine.push_content("fake", "content")


# --- Feedback reading ---


class TestReadFeedback:
    def _setup_session(self, tmp_path):
        engine = VisualEngine(project_dir=tmp_path)
        with patch("ydk.core.visual.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 123
            mock_popen.return_value = mock_proc
            session = engine.start_session()
        return engine, session

    def test_read_empty_feedback(self, tmp_path):
        engine, session = self._setup_session(tmp_path)
        events = engine.read_feedback(session.id)
        assert events == []

    def test_read_selection_event(self, tmp_path):
        engine, session = self._setup_session(tmp_path)
        event = {"type": "selection", "choice": "b", "choiceText": "Option B", "timestamp": 1700000000}
        feedback_path = Path(session.state_dir) / "feedback.jsonl"
        feedback_path.write_text(json.dumps(event) + "\n")

        events = engine.read_feedback(session.id)
        assert len(events) == 1
        assert isinstance(events[0], SelectionEvent)
        assert events[0].choice == "b"

    def test_read_element_annotation_event(self, tmp_path):
        engine, session = self._setup_session(tmp_path)
        event = {
            "type": "element_annotation",
            "id": "ann-1",
            "comment": "Fix this",
            "anchor": {"cssSelector": "div.test", "elementTag": "DIV"},
            "timestamp": 1700000000,
        }
        feedback_path = Path(session.state_dir) / "feedback.jsonl"
        feedback_path.write_text(json.dumps(event) + "\n")

        events = engine.read_feedback(session.id)
        assert len(events) == 1
        assert isinstance(events[0], ElementAnnotationEvent)
        assert events[0].comment == "Fix this"

    def test_read_rectangle_annotation_event(self, tmp_path):
        engine, session = self._setup_session(tmp_path)
        event = {
            "type": "rectangle_annotation",
            "id": "ann-2",
            "comment": "Needs spacing",
            "rect": {"xPct": 0.1, "yPct": 0.2, "wPct": 0.8, "hPct": 0.3},
            "timestamp": 1700000000,
        }
        feedback_path = Path(session.state_dir) / "feedback.jsonl"
        feedback_path.write_text(json.dumps(event) + "\n")

        events = engine.read_feedback(session.id)
        assert len(events) == 1
        assert isinstance(events[0], RectangleAnnotationEvent)

    def test_read_multiple_events(self, tmp_path):
        engine, session = self._setup_session(tmp_path)
        lines = [
            json.dumps({"type": "selection", "choice": "a", "timestamp": 1}),
            json.dumps({"type": "selection", "choice": "b", "timestamp": 2}),
        ]
        feedback_path = Path(session.state_dir) / "feedback.jsonl"
        feedback_path.write_text("\n".join(lines) + "\n")

        events = engine.read_feedback(session.id)
        assert len(events) == 2

    def test_read_skips_malformed_lines(self, tmp_path):
        engine, session = self._setup_session(tmp_path)
        lines = [
            "not json at all",
            json.dumps({"type": "selection", "choice": "a", "timestamp": 1}),
            '{"type": "unknown_type", "x": 1}',
            "",
        ]
        feedback_path = Path(session.state_dir) / "feedback.jsonl"
        feedback_path.write_text("\n".join(lines) + "\n")

        events = engine.read_feedback(session.id)
        assert len(events) == 1

    def test_read_feedback_nonexistent_session_raises(self, tmp_path):
        engine = VisualEngine(project_dir=tmp_path)
        with pytest.raises(ValueError, match="not found"):
            engine.read_feedback("nonexistent")


# --- Clear feedback ---


class TestClearFeedback:
    def test_clear_feedback(self, tmp_path):
        engine = VisualEngine(project_dir=tmp_path)
        with patch("ydk.core.visual.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 123
            mock_popen.return_value = mock_proc
            session = engine.start_session()

        feedback_path = Path(session.state_dir) / "feedback.jsonl"
        feedback_path.write_text('{"type":"selection","choice":"a","timestamp":1}\n')
        assert feedback_path.read_text().strip() != ""

        engine.clear_feedback(session.id)
        assert feedback_path.read_text() == ""

    def test_clear_feedback_nonexistent_session_raises(self, tmp_path):
        engine = VisualEngine(project_dir=tmp_path)
        with pytest.raises(ValueError, match="not found"):
            engine.clear_feedback("nonexistent")


# --- Screenshot ---


class TestCaptureScreenshot:
    def test_capture_screenshot_calls_playwright(self, tmp_path):
        engine = VisualEngine(project_dir=tmp_path)
        with patch("ydk.core.visual.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 123
            mock_popen.return_value = mock_proc
            session = engine.start_session()

        output = tmp_path / "shot.png"
        with patch("ydk.core.visual.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = engine.capture_screenshot(session.id, "http://localhost:3000", output)

        assert result == output
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert "playwright" in str(call_args)

    def test_capture_screenshot_nonexistent_session_raises(self, tmp_path):
        engine = VisualEngine(project_dir=tmp_path)
        with pytest.raises(ValueError, match="not found"):
            engine.capture_screenshot("fake", "http://localhost:3000", tmp_path / "out.png")

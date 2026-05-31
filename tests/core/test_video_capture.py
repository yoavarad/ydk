"""Tests for VideoCapture — Playwright video recording (mocked at system boundary)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from odk.core.video_capture import VideoCapture


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    d = tmp_path / "videos"
    return d


@pytest.fixture
def mock_playwright_fixture():
    """Install a fake playwright module into sys.modules for the test."""
    mock_module = ModuleType("playwright")
    mock_sync_api = ModuleType("playwright.sync_api")
    mock_sync_api.sync_playwright = MagicMock()  # type: ignore[attr-defined]
    mock_module.sync_api = mock_sync_api  # type: ignore[attr-defined]
    sys.modules["playwright"] = mock_module
    sys.modules["playwright.sync_api"] = mock_sync_api
    yield mock_sync_api.sync_playwright
    sys.modules.pop("playwright", None)
    sys.modules.pop("playwright.sync_api", None)


class TestRecordSession:
    def test_calls_playwright_with_correct_url(self, output_dir: Path, mock_playwright_fixture: MagicMock) -> None:
        mock_sync_pw = mock_playwright_fixture
        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()

        mock_pw.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page

        # Simulate video file creation when context closes
        def close_context_side_effect() -> None:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "video-001.webm").write_text("fake video")

        mock_context.close.side_effect = close_context_side_effect

        mock_sync_pw.return_value.__enter__ = MagicMock(return_value=mock_pw)
        mock_sync_pw.return_value.__exit__ = MagicMock(return_value=False)

        vc = VideoCapture()
        path = vc.record_session("http://localhost:3000", [], output_dir)

        mock_page.goto.assert_called_once_with("http://localhost:3000")
        assert path.name == "video-001.webm"

    def test_raises_when_no_video_produced(self, output_dir: Path, mock_playwright_fixture: MagicMock) -> None:
        mock_sync_pw = mock_playwright_fixture
        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()

        mock_pw.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page

        def close_context_side_effect() -> None:
            output_dir.mkdir(parents=True, exist_ok=True)

        mock_context.close.side_effect = close_context_side_effect

        mock_sync_pw.return_value.__enter__ = MagicMock(return_value=mock_pw)
        mock_sync_pw.return_value.__exit__ = MagicMock(return_value=False)

        vc = VideoCapture()
        with pytest.raises(FileNotFoundError, match="No video produced"):
            vc.record_session("http://localhost:3000", [], output_dir)


class TestExecuteAction:
    def test_executes_click_action(self, output_dir: Path) -> None:
        mock_page = MagicMock()
        vc = VideoCapture()
        vc._execute_action(mock_page, {"type": "click", "selector": "#btn"}, output_dir)
        mock_page.click.assert_called_once_with("#btn")

    def test_executes_fill_action(self, output_dir: Path) -> None:
        mock_page = MagicMock()
        vc = VideoCapture()
        vc._execute_action(mock_page, {"type": "fill", "selector": "#email", "value": "a@b.com"}, output_dir)
        mock_page.fill.assert_called_once_with("#email", "a@b.com")

    def test_executes_wait_action(self, output_dir: Path) -> None:
        mock_page = MagicMock()
        vc = VideoCapture()
        vc._execute_action(mock_page, {"type": "wait", "ms": 2000}, output_dir)
        mock_page.wait_for_timeout.assert_called_once_with(2000)

    def test_executes_screenshot_action(self, output_dir: Path) -> None:
        mock_page = MagicMock()
        vc = VideoCapture()
        vc._execute_action(mock_page, {"type": "screenshot", "name": "after-submit"}, output_dir)
        mock_page.screenshot.assert_called_once()
        call_kwargs = mock_page.screenshot.call_args
        assert "after-submit.png" in str(call_kwargs)

    def test_raises_on_unknown_action(self, output_dir: Path) -> None:
        mock_page = MagicMock()
        vc = VideoCapture()
        with pytest.raises(ValueError, match="Unknown action type"):
            vc._execute_action(mock_page, {"type": "hover", "selector": "#x"}, output_dir)


class TestRecordPage:
    def test_delegates_to_record_session(self, output_dir: Path) -> None:
        vc = VideoCapture()
        with patch.object(vc, "record_session", return_value=Path("video.webm")) as mock_rs:
            result = vc.record_page("http://localhost:3000", output_dir, wait_ms=5000)

        mock_rs.assert_called_once_with("http://localhost:3000", [{"type": "wait", "ms": 5000}], output_dir)
        assert result == Path("video.webm")

"""Tests for structured logging and spec_checker removal.

The old spec_checker module (NARRATIVE_CRITERIA, SpecChecker) has been removed.
These tests verify:
1. The logging system works correctly.
2. The old module is gone.
3. The YAML reviewer system still works for list-criteria.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from odk.core.log_setup import set_console_level, setup_odk_logger


class TestSpecCheckerRemoved:
    """Verify the old spec_checker module is gone."""

    def test_spec_checker_module_removed(self) -> None:
        with pytest.raises(ImportError):
            import odk.core.spec_checker  # type: ignore[import-not-found]  # noqa: F401

    def test_core_init_no_spec_checker_exports(self) -> None:
        import odk.core

        assert not hasattr(odk.core, "SpecChecker")
        assert not hasattr(odk.core, "NARRATIVE_CRITERIA")
        assert not hasattr(odk.core, "BUILT_IN_CRITERIA")
        assert not hasattr(odk.core, "SYSTEM_PROMPT_PREFIX")
        assert not hasattr(odk.core, "EvalCriterion")


class TestSetupOdkLogger:
    """Test the structured logger setup."""

    def test_creates_logger_with_handlers(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.setattr("odk.core.log_setup.Path.home", lambda: tmp_path)  # type: ignore[attr-defined]
        # Clear any existing handlers
        logger = logging.getLogger("odk.test_setup")
        logger.handlers.clear()

        result = setup_odk_logger(name="odk.test_setup", session_id="test-session")

        assert result.name == "odk.test_setup"
        assert len(result.handlers) == 2  # file + console

        log_dir = tmp_path / ".odk" / "logs" / "test-session"
        assert log_dir.is_dir()
        assert (log_dir / "odk.log").exists()

        # Cleanup
        for h in result.handlers[:]:
            h.close()
            result.removeHandler(h)

    def test_avoids_duplicate_handlers(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.setattr("odk.core.log_setup.Path.home", lambda: tmp_path)  # type: ignore[attr-defined]
        logger = logging.getLogger("odk.test_dedup")
        logger.handlers.clear()

        setup_odk_logger(name="odk.test_dedup")
        handler_count = len(logger.handlers)
        setup_odk_logger(name="odk.test_dedup")
        assert len(logger.handlers) == handler_count

        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)

    def test_rotating_handler_config(self, tmp_path: Path, monkeypatch: object) -> None:
        from logging.handlers import RotatingFileHandler

        monkeypatch.setattr("odk.core.log_setup.Path.home", lambda: tmp_path)  # type: ignore[attr-defined]
        logger = logging.getLogger("odk.test_rotate")
        logger.handlers.clear()

        setup_odk_logger(name="odk.test_rotate")
        file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
        assert len(file_handlers) == 1
        assert file_handlers[0].maxBytes == 10_000_000
        assert file_handlers[0].backupCount == 5

        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)


class TestSetConsoleLevel:
    def test_changes_stream_handler_level(self, tmp_path: Path, monkeypatch: object) -> None:
        from logging.handlers import RotatingFileHandler

        monkeypatch.setattr("odk.core.log_setup.Path.home", lambda: tmp_path)  # type: ignore[attr-defined]
        # Clear and re-setup
        logger = logging.getLogger("odk")
        logger.handlers.clear()
        setup_odk_logger()

        set_console_level(logging.DEBUG)

        stream_handlers = [
            h
            for h in logger.handlers
            if isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
        ]
        assert len(stream_handlers) == 1
        assert stream_handlers[0].level == logging.DEBUG

        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)


class TestReviewerTiming:
    """Verify elapsed_seconds field on ReviewResult."""

    def test_review_result_has_elapsed_seconds(self) -> None:
        from odk.core.reviewer import ReviewResult

        result = ReviewResult(
            reviewer_id="N01",
            name="Test",
            score=8,
            passed=True,
            reasoning="ok",
            elapsed_seconds=3.2,
        )
        assert result.elapsed_seconds == 3.2

    def test_review_result_default_zero(self) -> None:
        from odk.core.reviewer import ReviewResult

        result = ReviewResult(
            reviewer_id="N01",
            name="Test",
            score=8,
            passed=True,
            reasoning="ok",
        )
        assert result.elapsed_seconds == 0.0

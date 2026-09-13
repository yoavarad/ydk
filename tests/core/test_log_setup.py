"""Tests for ydk.core.log_setup UTF-8 encoding behavior."""

from __future__ import annotations

from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

from ydk.core.log_setup import setup_ydk_logger

if TYPE_CHECKING:
    import logging


def _get_file_handler(logger: logging.Logger) -> RotatingFileHandler:
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            return handler
    raise AssertionError("No RotatingFileHandler found on logger")


def test_file_handler_uses_utf8_encoding(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    logger = setup_ydk_logger(name=f"ydk-test-{tmp_path.name}")
    try:
        handler = _get_file_handler(logger)
        assert handler.encoding == "utf-8"
    finally:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


def test_non_ascii_message_round_trips_through_log_file(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    logger_name = f"ydk-test-nonascii-{tmp_path.name}"
    logger = setup_ydk_logger(name=logger_name)
    try:
        handler = _get_file_handler(logger)
        logger.debug("test → arrow")
        handler.flush()
        handler.close()

        log_path = tmp_path / ".ydk" / "logs" / "ydk.log"
        content = log_path.read_text(encoding="utf-8")
        assert "test → arrow" in content
        assert "�" not in content
    finally:
        for h in list(logger.handlers):
            h.close()
            logger.removeHandler(h)

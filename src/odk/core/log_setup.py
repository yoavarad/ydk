"""Structured logging for ODK with file + console handlers."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_odk_logger(
    name: str = "odk",
    level: int = logging.DEBUG,
    session_id: str | None = None,
) -> logging.Logger:
    """Configure ODK's structured logger with file + console handlers."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    # Log directory: ~/.odk/logs/
    log_dir = Path.home() / ".odk" / "logs"
    if session_id:
        log_dir = log_dir / session_id
    log_dir.mkdir(parents=True, exist_ok=True)

    # Rotating file handler (10MB max, 5 backups)
    file_handler = RotatingFileHandler(
        log_dir / "odk.log",
        maxBytes=10_000_000,
        backupCount=5,
    )
    file_handler.setLevel(logging.DEBUG)

    # Structured format with timestamps for profiling
    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler (WARNING+ only, unless --verbose)
    console_handler = logging.StreamHandler()
    console_level_str = os.environ.get("ODK_LOG_LEVEL", "")
    if console_level_str:
        console_handler.setLevel(getattr(logging, console_level_str.upper(), logging.WARNING))
    else:
        console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def set_console_level(level: int) -> None:
    """Update the console handler level on the root ODK logger.

    Called by the CLI when ``--verbose`` is passed.
    """
    logger = logging.getLogger("odk")
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler):
            handler.setLevel(level)

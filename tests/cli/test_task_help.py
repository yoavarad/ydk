"""Help-output tests: `ydk task` group text documents the lifecycle, `close` and `sync`."""

from __future__ import annotations

import re

from typer.testing import CliRunner

from ydk.cli import app

runner = CliRunner()


def _help(*args: str) -> str:
    result = runner.invoke(app, [*args, "--help"], env={"COLUMNS": "200", "NO_COLOR": "1"})
    assert result.exit_code == 0
    return re.sub(r"\s+", " ", result.output)


def _group_text() -> str:
    """Group help text only: everything before the Options panel (Commands lists close/sync anyway)."""
    return _help("task").split("┌", 1)[0]


class TestTaskGroupHelp:
    def test_group_help_mentions_close_and_sync(self) -> None:
        text = _group_text()
        assert "start" in text
        assert "close" in text
        assert "sync" in text

    def test_group_help_describes_lifecycle_order(self) -> None:
        text = _group_text()
        assert re.search(r"start\s*->\s*done\s*->\s*\(?merge\)?\s*->\s*close", text)

    def test_group_help_keeps_summary_line(self) -> None:
        assert "Task management and validation" in _group_text()


class TestTaskSyncHelp:
    def test_sync_help_mentions_close(self) -> None:
        text = _help("task", "sync")
        assert "ydk task close" in text

    def test_sync_help_says_bulk(self) -> None:
        assert "bulk" in _help("task", "sync").lower()

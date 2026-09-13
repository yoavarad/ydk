"""Tests for UTF-8 stdout/stderr reconfiguration in ydk.cli.__init__."""

from __future__ import annotations

from unittest.mock import Mock, patch

from ydk.cli import _reconfigure_streams_utf8


def test_reconfigure_streams_utf8_calls_reconfigure_on_supporting_streams():
    stream = Mock()
    with patch("sys.stdout", stream), patch("sys.stderr", stream):
        _reconfigure_streams_utf8()
    assert stream.reconfigure.call_count == 2
    stream.reconfigure.assert_called_with(encoding="utf-8", errors="replace")


def test_reconfigure_streams_utf8_ignores_streams_without_reconfigure():
    stream = Mock(spec=[])
    assert not hasattr(stream, "reconfigure")
    with patch("sys.stdout", stream), patch("sys.stderr", stream):
        # Should not raise even though the stream lacks .reconfigure()
        _reconfigure_streams_utf8()

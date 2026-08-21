"""Tests for the shared rich Console singleton's Windows encoding safety."""

from __future__ import annotations

import importlib
import io
import sys

# `ydk.output`'s __init__.py does `from ydk.output.console import console`,
# which shadows the `console` attribute on the `ydk.output` package with the
# Console *instance* -- so `import ydk.output.console as x`'s attribute-chain
# resolution would hand us that instance rather than the submodule.
# `importlib.import_module` goes through sys.modules directly instead,
# sidestepping the shadowed attribute.
console_module = importlib.import_module("ydk.output.console")


class TestReconfigureEncoding:
    def test_reconfigures_stdout_and_stderr_to_utf8(self, monkeypatch) -> None:
        fake_stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        fake_stderr = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        monkeypatch.setattr(sys, "stdout", fake_stdout)
        monkeypatch.setattr(sys, "stderr", fake_stderr)

        importlib.reload(console_module)

        assert fake_stdout.encoding == "utf-8"
        assert fake_stdout.errors == "replace"
        assert fake_stderr.encoding == "utf-8"
        assert fake_stderr.errors == "replace"

    def test_skips_reconfigure_when_stream_lacks_it(self, monkeypatch) -> None:
        """A stream without .reconfigure (e.g. some test harness replacements) must not crash import."""

        class NoReconfigure:
            pass

        monkeypatch.setattr(sys, "stdout", NoReconfigure())
        monkeypatch.setattr(sys, "stderr", NoReconfigure())

        importlib.reload(console_module)  # must not raise


class TestLegacyWindowsDisabled:
    def test_console_and_err_console_disable_legacy_windows_renderer(self) -> None:
        importlib.reload(console_module)

        assert console_module.console.legacy_windows is False
        assert console_module.err_console.legacy_windows is False

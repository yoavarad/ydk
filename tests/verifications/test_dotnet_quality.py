"""Tests for the dotnet-quality verification plugin.

Covers: the VERIFICATIONS bundle list (dotnet-build + dotnet-format only,
never dotnet-test), that main() subprocess-invokes exactly those two
sibling plugins' check.py scripts, and that the bundle's own ``passed``
field aggregates both sub-results correctly.
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    import types

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "dotnet-quality" / "check.py"


def _load_check_module() -> types.ModuleType:
    """Import dotnet-quality's check.py as a module for direct testing."""
    spec = importlib.util.spec_from_file_location("dotnet_quality_check", CHECK_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_main(monkeypatch: pytest.MonkeyPatch, mod: types.ModuleType, context: dict) -> dict:
    """Run mod.main() with stdin/stdout redirected, return the parsed result."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(context)))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    with pytest.raises(SystemExit):
        mod.main()
    return json.loads(out.getvalue())


def test_verifications_bundle_is_build_and_format_only() -> None:
    """The bundle runs dotnet-build + dotnet-format, in that order, and never dotnet-test."""
    mod = _load_check_module()
    assert mod.VERIFICATIONS == ["dotnet-build", "dotnet-format"]


class TestMainInvocations:
    """main() subprocess-invokes exactly dotnet-build and dotnet-format, never dotnet-test."""

    def _sub_result(self, name: str, passed: bool, output: str = "") -> str:
        return json.dumps(
            {
                "name": name,
                "passed": passed,
                "output": output,
                "duration_seconds": 0.1,
                "detail": None,
            }
        )

    def test_invokes_dotnet_build_and_dotnet_format_but_never_dotnet_test(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mod = _load_check_module()
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            calls.append(cmd)
            if "dotnet-build" in cmd[1]:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout=self._sub_result("dotnet-build", True)
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=self._sub_result("dotnet-format", True))

        with patch("subprocess.run", side_effect=fake_run):
            _run_main(monkeypatch, mod, {"project_root": str(tmp_path)})

        joined = [" ".join(cmd) for cmd in calls]
        assert any("dotnet-build" in cmd and cmd.endswith("check.py") for cmd in joined)
        assert any("dotnet-format" in cmd and cmd.endswith("check.py") for cmd in joined)
        assert not any("dotnet-test" in cmd for cmd in joined)

    def test_passes_when_both_sub_checks_pass(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module()

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if "dotnet-build" in cmd[1]:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout=self._sub_result("dotnet-build", True)
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=self._sub_result("dotnet-format", True))

        with patch("subprocess.run", side_effect=fake_run):
            data = _run_main(monkeypatch, mod, {"project_root": str(tmp_path)})

        assert data["passed"] is True

    def test_fails_when_dotnet_build_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module()

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if "dotnet-build" in cmd[1]:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout=self._sub_result("dotnet-build", False, "error CS1002")
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=self._sub_result("dotnet-format", True))

        with patch("subprocess.run", side_effect=fake_run):
            data = _run_main(monkeypatch, mod, {"project_root": str(tmp_path)})

        assert data["passed"] is False
        assert "error CS1002" in data["output"]

    def test_fails_when_dotnet_format_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module()

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if "dotnet-build" in cmd[1]:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout=self._sub_result("dotnet-build", True)
                )
            return subprocess.CompletedProcess(
                args=cmd, returncode=1, stdout=self._sub_result("dotnet-format", False, "needs formatting: Foo.cs")
            )

        with patch("subprocess.run", side_effect=fake_run):
            data = _run_main(monkeypatch, mod, {"project_root": str(tmp_path)})

        assert data["passed"] is False
        assert "needs formatting: Foo.cs" in data["output"]

    def test_both_subprocesses_run_even_when_first_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both sub-checks always run -- no short-circuiting on the first failure."""
        mod = _load_check_module()
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            calls.append(cmd)
            if "dotnet-build" in cmd[1]:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout=self._sub_result("dotnet-build", False, "build broke")
                )
            return subprocess.CompletedProcess(
                args=cmd, returncode=1, stdout=self._sub_result("dotnet-format", False, "format broke")
            )

        with patch("subprocess.run", side_effect=fake_run):
            data = _run_main(monkeypatch, mod, {"project_root": str(tmp_path)})

        assert len(calls) == 2
        assert data["passed"] is False
        assert "build broke" in data["output"]
        assert "format broke" in data["output"]

    def test_treats_invalid_json_stdout_as_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A crashed sub-plugin (non-JSON stdout) is a failure, not an unhandled exception."""
        mod = _load_check_module()

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if "dotnet-build" in cmd[1]:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="Traceback: boom")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=self._sub_result("dotnet-format", True))

        with patch("subprocess.run", side_effect=fake_run):
            data = _run_main(monkeypatch, mod, {"project_root": str(tmp_path)})

        assert data["passed"] is False

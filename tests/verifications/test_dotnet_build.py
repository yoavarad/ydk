"""Tests for the dotnet-build verification plugin.

Covers: fail-open when the .NET SDK is missing (including the bare
``dotnet`` muxer with no SDK registered), fail-open when no .sln/.csproj
is present, deterministic (sorted) target selection when multiple
solution files exist, ``.slnx`` files being ignored, and build
pass/fail mapping to the result's ``passed`` field.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    import types

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "dotnet-build" / "check.py"


def _load_check_module() -> types.ModuleType:
    """Import dotnet-build's check.py as a module for direct testing."""
    spec = importlib.util.spec_from_file_location("dotnet_build_check", CHECK_SCRIPT)
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


def test_skips_when_dotnet_not_on_path(tmp_path: Path) -> None:
    """When dotnet isn't installed, the plugin passes (skips) instead of crashing."""
    env = dict(os.environ)
    env["PATH"] = ""
    result = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        input=json.dumps({"project_root": str(tmp_path)}),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["passed"] is True
    assert "dotnet SDK not found" in data["output"]


class TestHasSdk:
    """_has_sdk treats a bare muxer (zero exit, empty stdout) as no-SDK."""

    def test_true_when_sdks_listed(self) -> None:
        mod = _load_check_module()
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="8.0.100 [/usr/share/dotnet/sdk]\n")
        with patch("subprocess.run", return_value=fake):
            assert mod._has_sdk("dotnet") is True

    def test_false_when_muxer_has_no_sdk(self) -> None:
        """Bare dotnet.exe muxer: zero exit code but empty stdout."""
        mod = _load_check_module()
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
        with patch("subprocess.run", return_value=fake):
            assert mod._has_sdk("dotnet") is False

    def test_false_when_nonzero_exit(self) -> None:
        mod = _load_check_module()
        fake = subprocess.CompletedProcess(args=[], returncode=1, stdout="")
        with patch("subprocess.run", return_value=fake):
            assert mod._has_sdk("dotnet") is False

    def test_false_on_timeout(self) -> None:
        mod = _load_check_module()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="dotnet", timeout=15)):
            assert mod._has_sdk("dotnet") is False

    def test_false_on_oserror(self) -> None:
        mod = _load_check_module()
        with patch("subprocess.run", side_effect=OSError):
            assert mod._has_sdk("dotnet") is False


class TestFindBuildTarget:
    """_find_build_target discovers .sln first, falls back to .csproj."""

    def test_none_when_no_project_files(self, tmp_path: Path) -> None:
        mod = _load_check_module()
        assert mod._find_build_target(str(tmp_path)) is None

    def test_picks_sorted_first_sln_when_multiple_present(self, tmp_path: Path) -> None:
        (tmp_path / "z.sln").write_text("")
        (tmp_path / "a.sln").write_text("")
        (tmp_path / "m.sln").write_text("")
        mod = _load_check_module()

        target = mod._find_build_target(str(tmp_path))

        assert target == str(tmp_path / "a.sln")

    def test_falls_back_to_csproj_when_no_sln(self, tmp_path: Path) -> None:
        (tmp_path / "z.csproj").write_text("")
        (tmp_path / "a.csproj").write_text("")
        mod = _load_check_module()

        target = mod._find_build_target(str(tmp_path))

        assert target == str(tmp_path / "a.csproj")

    def test_ignores_slnx_files(self, tmp_path: Path) -> None:
        """.slnx is excluded entirely -- falls through to .csproj, not matched as a solution."""
        (tmp_path / "app.slnx").write_text("")
        (tmp_path / "app.csproj").write_text("")
        mod = _load_check_module()

        target = mod._find_build_target(str(tmp_path))

        assert target == str(tmp_path / "app.csproj")

    def test_none_when_only_slnx_present(self, tmp_path: Path) -> None:
        (tmp_path / "app.slnx").write_text("")
        mod = _load_check_module()

        assert mod._find_build_target(str(tmp_path)) is None

    def test_skips_excluded_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "generated.sln").write_text("")
        (tmp_path / "obj").mkdir()
        (tmp_path / "obj" / "generated.csproj").write_text("")
        mod = _load_check_module()

        assert mod._find_build_target(str(tmp_path)) is None


class TestMain:
    """End-to-end behavior of main() with subprocess and dotnet discovery mocked."""

    def test_fails_open_when_no_project_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module()
        fake_sdks = subprocess.CompletedProcess(args=[], returncode=0, stdout="8.0.100\n")
        with (
            patch("shutil.which", return_value="/usr/bin/dotnet"),
            patch("subprocess.run", return_value=fake_sdks),
        ):
            data = _run_main(monkeypatch, mod, {"project_root": str(tmp_path)})

        assert data["passed"] is True
        assert "No .sln/.csproj found" in data["output"]

    def test_build_pass_maps_to_passed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "app.sln").write_text("")
        mod = _load_check_module()

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if "--list-sdks" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="8.0.100\n")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="Build succeeded.", stderr="")

        with (
            patch("shutil.which", return_value="/usr/bin/dotnet"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            data = _run_main(monkeypatch, mod, {"project_root": str(tmp_path)})

        assert data["passed"] is True
        assert data["detail"]["target"] == str(tmp_path / "app.sln")

    def test_build_fail_maps_to_failed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "app.sln").write_text("")
        mod = _load_check_module()

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if "--list-sdks" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="8.0.100\n")
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="error CS1002")

        with (
            patch("shutil.which", return_value="/usr/bin/dotnet"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            data = _run_main(monkeypatch, mod, {"project_root": str(tmp_path)})

        assert data["passed"] is False
        assert "error CS1002" in data["output"]

    def test_skips_when_only_non_dotnet_files_changed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """changed_files present but none touch .cs/.csproj/.sln -> skip without invoking dotnet CLI."""
        mod = _load_check_module()
        with patch("subprocess.run") as mock_run:
            data = _run_main(monkeypatch, mod, {"project_root": str(tmp_path), "changed_files": ["README.md"]})
        mock_run.assert_not_called()
        assert data["passed"] is True
        assert "skipped" in data["output"].lower()

    def test_runs_normally_when_cs_file_changed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """changed_files present and includes a .cs file -> normal flow continues."""
        mod = _load_check_module()
        fake_sdks = subprocess.CompletedProcess(args=[], returncode=0, stdout="8.0.100\n")
        with (
            patch("shutil.which", return_value="/usr/bin/dotnet"),
            patch("subprocess.run", return_value=fake_sdks),
        ):
            data = _run_main(monkeypatch, mod, {"project_root": str(tmp_path), "changed_files": ["src/Foo.cs"]})
        assert data["passed"] is True
        assert "No .sln/.csproj found" in data["output"]

    def test_absent_changed_files_runs_unconditionally(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No changed_files key at all (older caller) -> current unconditional behavior preserved."""
        mod = _load_check_module()
        fake_sdks = subprocess.CompletedProcess(args=[], returncode=0, stdout="8.0.100\n")
        with (
            patch("shutil.which", return_value="/usr/bin/dotnet"),
            patch("subprocess.run", return_value=fake_sdks),
        ):
            data = _run_main(monkeypatch, mod, {"project_root": str(tmp_path)})
        assert data["passed"] is True
        assert "No .sln/.csproj found" in data["output"]

    def test_runs_normally_when_uppercase_cs_extension_changed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Extension match is case-insensitive -- 'Main.CS' must not be skipped."""
        mod = _load_check_module()
        fake_sdks = subprocess.CompletedProcess(args=[], returncode=0, stdout="8.0.100\n")
        with (
            patch("shutil.which", return_value="/usr/bin/dotnet"),
            patch("subprocess.run", return_value=fake_sdks),
        ):
            data = _run_main(monkeypatch, mod, {"project_root": str(tmp_path), "changed_files": ["src/Main.CS"]})
        assert data["passed"] is True
        assert "No .sln/.csproj found" in data["output"]

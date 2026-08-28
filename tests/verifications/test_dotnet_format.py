"""Tests for the dotnet-format verification plugin.

Covers: fail-open when no .NET SDK is installed, fail-open when no .NET
project is found, deterministic target discovery when multiple .sln files
are present, .slnx files being ignored, and format-fail/format-pass result
mapping. All subprocess and dotnet-discovery calls are mocked -- these
tests do not require a real .NET SDK to be installed.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

if TYPE_CHECKING:
    import types

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "dotnet-format" / "check.py"


def _load_check_module() -> types.ModuleType:
    """Import dotnet-format's check.py as a module for direct testing."""
    spec = importlib.util.spec_from_file_location("dotnet_format_check", CHECK_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_result(returncode: int, stdout: str = "", stderr: str = "") -> object:
    """Build a minimal stand-in for subprocess.CompletedProcess."""
    return type("FakeCompletedProcess", (), {"returncode": returncode, "stdout": stdout, "stderr": stderr})()


def _run_main(
    mod: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    project_root: Path,
    changed_files: list[str] | None = None,
) -> dict:
    """Run mod.main() with stdin/stdout wired to an in-process context dict."""
    context: dict[str, object] = {"project_root": str(project_root)}
    if changed_files is not None:
        context["changed_files"] = changed_files
    stdin = io.StringIO(json.dumps(context))
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    with pytest.raises(SystemExit):
        mod.main()
    return json.loads(stdout.getvalue())


class TestHasSdk:
    """_has_sdk distinguishes a real SDK install from a bare dotnet muxer."""

    def test_true_when_list_sdks_succeeds_with_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module()
        monkeypatch.setattr(
            mod.subprocess,
            "run",
            lambda cmd, **kwargs: _fake_result(0, stdout="8.0.100 [C:\\Program Files\\dotnet\\sdk]\n"),
        )

        assert mod._has_sdk("dotnet") is True

    def test_false_when_bare_muxer_returns_empty_stdout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A bare dotnet.exe muxer with no SDK exits 0 but prints nothing."""
        mod = _load_check_module()
        monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kwargs: _fake_result(0, stdout=""))

        assert mod._has_sdk("dotnet") is False

    def test_false_when_command_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module()
        monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kwargs: _fake_result(1, stdout=""))

        assert mod._has_sdk("dotnet") is False

    def test_false_on_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _load_check_module()

        def raise_timeout(cmd, **kwargs):
            raise mod.subprocess.TimeoutExpired(cmd, 15)

        monkeypatch.setattr(mod.subprocess, "run", raise_timeout)

        assert mod._has_sdk("dotnet") is False


class TestFindFormatTarget:
    """_find_format_target discovers .sln first, falls back to .csproj, ignores .slnx."""

    def test_returns_none_when_nothing_found(self, tmp_path: Path) -> None:
        mod = _load_check_module()

        assert mod._find_format_target(str(tmp_path)) is None

    def test_picks_sorted_first_sln_when_multiple_present(self, tmp_path: Path) -> None:
        """Path.rglob order is filesystem-dependent -- candidates must be sorted."""
        (tmp_path / "Zeta.sln").write_text("")
        (tmp_path / "Alpha.sln").write_text("")
        (tmp_path / "Mid.sln").write_text("")
        mod = _load_check_module()

        target = mod._find_format_target(str(tmp_path))

        assert target is not None
        assert Path(target).name == "Alpha.sln"

    def test_falls_back_to_csproj_when_no_sln(self, tmp_path: Path) -> None:
        (tmp_path / "App.csproj").write_text("")
        mod = _load_check_module()

        target = mod._find_format_target(str(tmp_path))

        assert target is not None
        assert Path(target).name == "App.csproj"

    def test_picks_sorted_first_csproj_when_multiple_present(self, tmp_path: Path) -> None:
        (tmp_path / "Zeta.csproj").write_text("")
        (tmp_path / "Alpha.csproj").write_text("")
        mod = _load_check_module()

        target = mod._find_format_target(str(tmp_path))

        assert target is not None
        assert Path(target).name == "Alpha.csproj"

    def test_slnx_files_are_never_matched(self, tmp_path: Path) -> None:
        """.slnx fails dotnet format with a raw MSB4068 parse error -- excluded entirely."""
        (tmp_path / "App.slnx").write_text("")
        mod = _load_check_module()

        assert mod._find_format_target(str(tmp_path)) is None

    def test_slnx_ignored_falls_back_to_csproj(self, tmp_path: Path) -> None:
        (tmp_path / "App.slnx").write_text("")
        (tmp_path / "App.csproj").write_text("")
        mod = _load_check_module()

        target = mod._find_format_target(str(tmp_path))

        assert target is not None
        assert Path(target).name == "App.csproj"

    def test_skips_excluded_directories(self, tmp_path: Path) -> None:
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "Ignored.sln").write_text("")
        (tmp_path / "obj").mkdir()
        (tmp_path / "obj" / "Ignored2.sln").write_text("")
        (tmp_path / "Real.sln").write_text("")
        mod = _load_check_module()

        target = mod._find_format_target(str(tmp_path))

        assert target is not None
        assert Path(target).name == "Real.sln"


class TestMainFailOpen:
    """main() fails open (passes) when the SDK or a project is missing."""

    def test_passes_when_dotnet_not_on_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        mod = _load_check_module()
        monkeypatch.setattr(mod.shutil, "which", lambda name: None)

        data = _run_main(mod, monkeypatch, tmp_path)

        assert data["passed"] is True
        assert "not found" in data["output"].lower()

    def test_passes_when_dotnet_muxer_has_no_sdk(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        mod = _load_check_module()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "dotnet")
        monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kwargs: _fake_result(0, stdout=""))

        data = _run_main(mod, monkeypatch, tmp_path)

        assert data["passed"] is True

    def test_passes_when_no_project_found(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        mod = _load_check_module()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "dotnet")
        monkeypatch.setattr(mod, "_has_sdk", lambda dotnet_bin: True)

        data = _run_main(mod, monkeypatch, tmp_path)

        assert data["passed"] is True
        assert "no .sln/.csproj" in data["output"].lower()


class TestMainFormatResult:
    """main() maps the dotnet format exit code to the result's passed field."""

    def test_format_pass_maps_to_passed_true(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        (tmp_path / "App.sln").write_text("")
        mod = _load_check_module()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "dotnet")
        monkeypatch.setattr(mod, "_has_sdk", lambda dotnet_bin: True)
        monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kwargs: _fake_result(0))

        data = _run_main(mod, monkeypatch, tmp_path)

        assert data["passed"] is True
        assert data["detail"]["target"].endswith("App.sln")

    def test_format_fail_maps_to_passed_false(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        (tmp_path / "App.sln").write_text("")
        mod = _load_check_module()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "dotnet")
        monkeypatch.setattr(mod, "_has_sdk", lambda dotnet_bin: True)
        monkeypatch.setattr(
            mod.subprocess,
            "run",
            lambda cmd, **kwargs: _fake_result(2, stdout="Formatted code file 'Foo.cs' did not match run settings.\n"),
        )

        data = _run_main(mod, monkeypatch, tmp_path)

        assert data["passed"] is False
        assert "Foo.cs" in data["output"]


class TestChangedFilesScoping:
    """main() skips when changed_files is present but touches nothing .NET-related."""

    def test_skips_when_only_non_dotnet_files_changed(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        mod = _load_check_module()
        mock_run = Mock(side_effect=AssertionError("subprocess.run should not be called"))
        monkeypatch.setattr(mod.subprocess, "run", mock_run)

        data = _run_main(mod, monkeypatch, tmp_path, changed_files=["README.md"])

        mock_run.assert_not_called()
        assert data["passed"] is True
        assert "skipped" in data["output"].lower()

    def test_runs_normally_when_cs_file_changed(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        mod = _load_check_module()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "dotnet")
        monkeypatch.setattr(mod, "_has_sdk", lambda dotnet_bin: True)

        data = _run_main(mod, monkeypatch, tmp_path, changed_files=["src/Foo.cs"])

        assert data["passed"] is True
        assert "no .sln/.csproj" in data["output"].lower()

    def test_absent_changed_files_runs_unconditionally(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        mod = _load_check_module()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "dotnet")
        monkeypatch.setattr(mod, "_has_sdk", lambda dotnet_bin: True)

        data = _run_main(mod, monkeypatch, tmp_path)

        assert data["passed"] is True
        assert "no .sln/.csproj" in data["output"].lower()

    def test_runs_normally_when_uppercase_cs_extension_changed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Extension match is case-insensitive -- 'Main.CS' must not be skipped."""
        mod = _load_check_module()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "dotnet")
        monkeypatch.setattr(mod, "_has_sdk", lambda dotnet_bin: True)

        data = _run_main(mod, monkeypatch, tmp_path, changed_files=["src/Main.CS"])

        assert data["passed"] is True
        assert "no .sln/.csproj" in data["output"].lower()

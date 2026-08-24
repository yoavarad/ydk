"""Tests for the dotnet-test verification plugin.

Covers: fail-open when the .NET SDK isn't installed (including the bare
muxer-with-no-SDK case), fail-open when no .NET project is found, target
discovery (sorted .sln/.csproj candidates, .slnx exclusion, the Test/Tests
substring heuristic), and pass/fail mapping from ``dotnet test``'s exit code.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest

if TYPE_CHECKING:
    import types

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "dotnet-test" / "check.py"


def _load_check_module() -> types.ModuleType:
    """Import dotnet-test's check.py as a module for direct testing."""
    spec = importlib.util.spec_from_file_location("dotnet_test_check", CHECK_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_main(
    mod: types.ModuleType,
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    changed_files: list[str] | None = None,
) -> dict:
    """Invoke mod.main() with stdin set to a project_root context, return parsed stdout."""
    import io
    import sys

    context: dict[str, object] = {"project_root": str(project_root)}
    if changed_files is not None:
        context["changed_files"] = changed_files
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(context)))
    with contextlib.suppress(SystemExit):
        mod.main()
    return json.loads(capsys.readouterr().out)


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestHasSdk:
    """_has_sdk distinguishes a real SDK from a bare dotnet muxer."""

    def test_true_when_sdk_listed(self) -> None:
        mod = _load_check_module()
        with patch.object(
            mod.subprocess, "run", return_value=_completed(0, stdout="8.0.100 [C:\\Program Files\\dotnet\\sdk]\n")
        ):
            assert mod._has_sdk("dotnet") is True

    def test_false_when_muxer_has_no_sdk(self) -> None:
        """A bare dotnet.exe muxer returns exit 0 but empty stdout -- must count as no-SDK."""
        mod = _load_check_module()
        with patch.object(mod.subprocess, "run", return_value=_completed(0, stdout="")):
            assert mod._has_sdk("dotnet") is False

    def test_false_when_nonzero_exit(self) -> None:
        mod = _load_check_module()
        with patch.object(mod.subprocess, "run", return_value=_completed(1, stdout="")):
            assert mod._has_sdk("dotnet") is False

    def test_false_when_dotnet_missing_or_times_out(self) -> None:
        mod = _load_check_module()
        with patch.object(mod.subprocess, "run", side_effect=FileNotFoundError):
            assert mod._has_sdk("dotnet") is False
        with patch.object(mod.subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="dotnet", timeout=15)):
            assert mod._has_sdk("dotnet") is False


class TestFindTestTarget:
    """_find_test_target discovers .sln first, else a Test/Tests-looking .csproj."""

    def test_none_when_no_dotnet_files(self, tmp_path: Path) -> None:
        mod = _load_check_module()
        assert mod._find_test_target(str(tmp_path)) is None

    def test_sln_preferred_over_csproj(self, tmp_path: Path) -> None:
        mod = _load_check_module()
        (tmp_path / "App.sln").write_text("")
        (tmp_path / "App.Tests.csproj").write_text("")
        assert mod._find_test_target(str(tmp_path)) == str(tmp_path / "App.sln")

    def test_sorted_candidate_selection_with_multiple_sln(self, tmp_path: Path) -> None:
        """Path.rglob() order is filesystem-dependent -- must sort before picking [0]."""
        mod = _load_check_module()
        (tmp_path / "zzz").mkdir()
        (tmp_path / "aaa").mkdir()
        (tmp_path / "zzz" / "Zeta.sln").write_text("")
        (tmp_path / "aaa" / "Alpha.sln").write_text("")
        assert mod._find_test_target(str(tmp_path)) == str(tmp_path / "aaa" / "Alpha.sln")

    def test_sorted_candidate_selection_with_multiple_test_csproj(self, tmp_path: Path) -> None:
        mod = _load_check_module()
        (tmp_path / "Zeta.Tests.csproj").write_text("")
        (tmp_path / "Alpha.Tests.csproj").write_text("")
        assert mod._find_test_target(str(tmp_path)) == str(tmp_path / "Alpha.Tests.csproj")

    def test_slnx_files_ignored(self, tmp_path: Path) -> None:
        """.slnx isn't matched at all -- the .NET 8 SDK fails on it with a raw MSB4068 error."""
        mod = _load_check_module()
        (tmp_path / "App.slnx").write_text("")
        assert mod._find_test_target(str(tmp_path)) is None

    def test_slnx_ignored_falls_back_to_test_csproj(self, tmp_path: Path) -> None:
        mod = _load_check_module()
        (tmp_path / "App.slnx").write_text("")
        (tmp_path / "App.Tests.csproj").write_text("")
        assert mod._find_test_target(str(tmp_path)) == str(tmp_path / "App.Tests.csproj")

    def test_non_test_csproj_not_matched(self, tmp_path: Path) -> None:
        mod = _load_check_module()
        (tmp_path / "App.csproj").write_text("")
        assert mod._find_test_target(str(tmp_path)) is None

    @pytest.mark.parametrize("name", ["Foo.Tests.csproj", "FooTest.csproj", "Tests.csproj"])
    def test_test_tests_substring_heuristic_matches(self, tmp_path: Path, name: str) -> None:
        mod = _load_check_module()
        (tmp_path / name).write_text("")
        assert mod._find_test_target(str(tmp_path)) == str(tmp_path / name)

    def test_excluded_dirs_skipped(self, tmp_path: Path) -> None:
        mod = _load_check_module()
        for d in ["bin", "obj", ".git", ".ydk", ".vs", "node_modules"]:
            sub = tmp_path / d
            sub.mkdir()
            (sub / "Ignored.sln").write_text("")
        assert mod._find_test_target(str(tmp_path)) is None


class TestMain:
    """End-to-end main() behavior with subprocess entirely mocked."""

    def test_passes_when_dotnet_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load_check_module()
        with patch.object(mod.shutil, "which", return_value=None):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is True
        assert "skipped" in data["output"].lower()

    def test_passes_when_muxer_present_but_no_sdk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        mod = _load_check_module()
        with (
            patch.object(mod.shutil, "which", return_value="dotnet"),
            patch.object(mod.subprocess, "run", return_value=_completed(0, stdout="")),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is True
        assert "skipped" in data["output"].lower()

    def test_passes_when_no_test_project_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load_check_module()
        with (
            patch.object(mod.shutil, "which", return_value="dotnet"),
            patch.object(mod.subprocess, "run", return_value=_completed(0, stdout="8.0.100\n")),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is True
        assert "skipped" in data["output"].lower()

    def test_maps_dotnet_test_pass_to_passed_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        mod = _load_check_module()
        (tmp_path / "App.Tests.csproj").write_text("")
        responses = iter(
            [
                _completed(0, stdout="8.0.100\n"),  # --list-sdks
                _completed(0, stdout="Passed!  - Failed: 0, Passed: 3\n"),  # dotnet test
            ]
        )
        with (
            patch.object(mod.shutil, "which", return_value="dotnet"),
            patch.object(mod.subprocess, "run", side_effect=lambda *a, **k: next(responses)),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is True
        assert data["detail"]["target"] == str(tmp_path / "App.Tests.csproj")

    def test_maps_dotnet_test_fail_to_failed_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        mod = _load_check_module()
        (tmp_path / "App.Tests.csproj").write_text("")
        responses = iter(
            [
                _completed(0, stdout="8.0.100\n"),  # --list-sdks
                _completed(1, stdout="Failed!  - Failed: 2, Passed: 1\n"),  # dotnet test
            ]
        )
        with (
            patch.object(mod.shutil, "which", return_value="dotnet"),
            patch.object(mod.subprocess, "run", side_effect=lambda *a, **k: next(responses)),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is False


class TestChangedFilesScoping:
    """main() skips when changed_files is present but touches nothing .NET-related."""

    def test_skips_when_only_non_dotnet_files_changed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mod = _load_check_module()
        mock_run = Mock(side_effect=AssertionError("subprocess.run should not be called"))
        with patch.object(mod.subprocess, "run", mock_run):
            data = _run_main(mod, tmp_path, monkeypatch, capsys, changed_files=["README.md"])
        mock_run.assert_not_called()
        assert data["passed"] is True
        assert "skipped" in data["output"].lower()

    def test_runs_normally_when_cs_file_changed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mod = _load_check_module()
        with (
            patch.object(mod.shutil, "which", return_value="dotnet"),
            patch.object(mod.subprocess, "run", return_value=_completed(0, stdout="8.0.100\n")),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys, changed_files=["src/Foo.cs"])
        assert data["passed"] is True
        assert "skipped" in data["output"].lower()

    def test_absent_changed_files_runs_unconditionally(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mod = _load_check_module()
        with (
            patch.object(mod.shutil, "which", return_value="dotnet"),
            patch.object(mod.subprocess, "run", return_value=_completed(0, stdout="8.0.100\n")),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is True
        assert "skipped" in data["output"].lower()

    def test_runs_normally_when_uppercase_cs_extension_changed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Extension match is case-insensitive -- 'Main.CS' must not be skipped."""
        mod = _load_check_module()
        with (
            patch.object(mod.shutil, "which", return_value="dotnet"),
            patch.object(mod.subprocess, "run", return_value=_completed(0, stdout="8.0.100\n")),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys, changed_files=["src/Main.CS"])
        assert data["passed"] is True
        assert "No test project" in data["output"]

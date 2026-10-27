"""Tests for the dotnet-format verification plugin.

Covers: fail-open when no .NET SDK is installed, fail-open when no .NET
project is found, multi-target format runs (all .csproj when no solution),
.slnx use gated on SDK version, third_party exclusion, configured targets,
and format-fail/format-pass result mapping. Discovery itself is tested in
test_dotnet_target.py. All subprocess calls are mocked except one
real-subprocess smoke test -- no real .NET SDK is required.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
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


class TestMultiTarget:
    """main() formats every discovered target; .slnx only when the SDK supports it."""

    def _run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        version: str = "8.0.100",
        failing: str | None = None,
    ) -> tuple[dict, list[list[str]]]:
        mod = _load_check_module()
        format_calls: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs: object) -> object:
            if "--version" in cmd:
                return _fake_result(0, stdout=version + "\n")
            if "--list-sdks" in cmd:
                return _fake_result(0, stdout="8.0.100 [x]\n")
            format_calls.append(cmd)
            if failing and failing in cmd[2]:
                return _fake_result(2, stdout="bad format\n")
            return _fake_result(0, stdout="ok\n")

        monkeypatch.setattr(mod.shutil, "which", lambda name: "dotnet")
        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        return _run_main(mod, monkeypatch, tmp_path), format_calls

    def _two_projects(self, tmp_path: Path) -> None:
        for name in ("a", "b"):
            (tmp_path / name).mkdir()
            (tmp_path / name / f"{name.upper()}.csproj").write_text("")

    def test_all_csproj_formatted_when_no_solution(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self._two_projects(tmp_path)
        data, format_calls = self._run(monkeypatch, tmp_path)

        assert data["passed"] is True
        assert len(format_calls) == 2
        assert len(data["detail"]["targets"]) == 2
        assert "target" not in data["detail"]
        assert all(c[1] == "format" and c[-1] == "--verify-no-changes" for c in format_calls)
        assert "A.csproj ==" in data["output"]
        assert "B.csproj ==" in data["output"]

    def test_one_failing_target_fails_overall(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self._two_projects(tmp_path)
        data, format_calls = self._run(monkeypatch, tmp_path, failing="B.csproj")

        assert data["passed"] is False
        assert len(format_calls) == 2
        assert "bad format" in data["output"]

    def test_slnx_used_when_sdk_supports_it(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        (tmp_path / "App.slnx").write_text("")
        data, format_calls = self._run(monkeypatch, tmp_path, version="9.0.200")

        assert data["passed"] is True
        assert len(format_calls) == 1
        assert format_calls[0][2].endswith("App.slnx")
        assert data["detail"]["target"].endswith("App.slnx")

    def test_slnx_skipped_for_csproj_when_sdk_too_old(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        (tmp_path / "App.slnx").write_text("")
        (tmp_path / "App.csproj").write_text("")
        data, format_calls = self._run(monkeypatch, tmp_path, version="8.0.100")

        assert data["passed"] is True
        assert len(format_calls) == 1
        assert format_calls[0][2].endswith("App.csproj")

    def test_third_party_csproj_ignored(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        (tmp_path / "third_party").mkdir()
        (tmp_path / "third_party" / "Vendor.csproj").write_text("")
        (tmp_path / "Real.csproj").write_text("")
        data, format_calls = self._run(monkeypatch, tmp_path)

        assert len(format_calls) == 1
        assert format_calls[0][2].endswith("Real.csproj")
        assert data["passed"] is True


class TestBudget:
    """main() shares one total budget across targets and fails cleanly on timeout."""

    def _run(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, timeout_on_format: bool) -> tuple[dict, list[dict]]:
        mod = _load_check_module()
        format_calls: list[dict] = []

        def fake_run(cmd: list[str], **kwargs: object) -> object:
            if "--version" in cmd:
                return _fake_result(0, stdout="8.0.100\n")
            if "--list-sdks" in cmd:
                return _fake_result(0, stdout="8.0.100 [x]\n")
            format_calls.append({"cmd": cmd, **kwargs})
            if timeout_on_format:
                raise mod.subprocess.TimeoutExpired(cmd, kwargs["timeout"])
            return _fake_result(0, stdout="ok\n")

        monkeypatch.setattr(mod.shutil, "which", lambda name: "dotnet")
        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        for name in ("a", "b"):
            (tmp_path / name).mkdir()
            (tmp_path / name / f"{name.upper()}.csproj").write_text("")
        return _run_main(mod, monkeypatch, tmp_path), format_calls

    def test_timeout_fails_emits_json_and_stops(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        data, format_calls = self._run(monkeypatch, tmp_path, timeout_on_format=True)

        assert data["passed"] is False
        assert "timed out" in data["output"]
        assert len(format_calls) == 1

    def test_format_timeout_within_budget(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _, format_calls = self._run(monkeypatch, tmp_path, timeout_on_format=False)

        assert len(format_calls) == 2
        assert all(1.0 <= c["timeout"] <= 110 for c in format_calls)


class TestRealSubprocess:
    """Run check.py as a real subprocess -- proves the shared helper import works."""

    def test_no_dotnet_on_path_skips(self, tmp_path: Path) -> None:
        import subprocess

        proc = subprocess.run(
            [sys.executable, str(CHECK_SCRIPT)],
            input=json.dumps({"project_root": str(tmp_path)}),
            capture_output=True,
            text=True,
            env={**os.environ, "PATH": ""},
            check=False,
        )

        assert proc.returncode == 0
        assert "dotnet SDK not found" in proc.stdout


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
        assert "no .sln/.slnx/.csproj" in data["output"].lower()


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
        assert data["detail"]["status"] == "SKIPPED"
        assert data["detail"]["skip_reason"]

    def test_runs_normally_when_cs_file_changed(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        mod = _load_check_module()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "dotnet")
        monkeypatch.setattr(mod, "_has_sdk", lambda dotnet_bin: True)

        data = _run_main(mod, monkeypatch, tmp_path, changed_files=["src/Foo.cs"])

        assert data["passed"] is True
        assert "no .sln/.slnx/.csproj" in data["output"].lower()

    def test_absent_changed_files_runs_unconditionally(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        mod = _load_check_module()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "dotnet")
        monkeypatch.setattr(mod, "_has_sdk", lambda dotnet_bin: True)

        data = _run_main(mod, monkeypatch, tmp_path)

        assert data["passed"] is True
        assert "no .sln/.slnx/.csproj" in data["output"].lower()

    def test_runs_normally_when_uppercase_cs_extension_changed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Extension match is case-insensitive -- 'Main.CS' must not be skipped."""
        mod = _load_check_module()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "dotnet")
        monkeypatch.setattr(mod, "_has_sdk", lambda dotnet_bin: True)

        data = _run_main(mod, monkeypatch, tmp_path, changed_files=["src/Main.CS"])

        assert data["passed"] is True
        assert "no .sln/.slnx/.csproj" in data["output"].lower()


class TestConfiguredTarget:
    """verification.dotnet.target overrides auto-discovery in context["config"]."""

    def _run(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, target: str) -> tuple[dict, list[list[str]]]:
        import io
        import sys

        mod = _load_check_module()
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs: object) -> object:
            calls.append(cmd)
            return type("R", (), {"returncode": 0, "stdout": "8.0.100\n", "stderr": ""})()

        monkeypatch.setattr(mod.shutil, "which", lambda name: "dotnet")
        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        context = {"project_root": str(tmp_path), "config": {"dotnet": {"target": target}}}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(context)))
        out = io.StringIO()
        monkeypatch.setattr(sys, "stdout", out)
        with pytest.raises(SystemExit):
            mod.main()
        return json.loads(out.getvalue()), calls

    def test_configured_target_used_over_first_sln(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        (tmp_path / "a.sln").write_text("")
        (tmp_path / "z.sln").write_text("")
        data, calls = self._run(monkeypatch, tmp_path, "z.sln")
        assert data["passed"] is True
        assert data["detail"]["target"] == str((tmp_path / "z.sln").resolve())
        assert str((tmp_path / "z.sln").resolve()) in calls[-1]
        assert str((tmp_path / "a.sln").resolve()) not in calls[-1]

    def test_missing_configured_target_fails_clearly(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        (tmp_path / "a.sln").write_text("")
        data, calls = self._run(monkeypatch, tmp_path, "nope.sln")
        assert data["passed"] is False
        assert "verification.dotnet.target" in data["output"]
        assert "nope.sln" in data["output"]
        assert all("--list-sdks" in c for c in calls)

    def test_configured_slnx_accepted(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        (tmp_path / "app.slnx").write_text("")
        data, calls = self._run(monkeypatch, tmp_path, "app.slnx")
        assert data["passed"] is True
        assert data["detail"]["target"] == str((tmp_path / "app.slnx").resolve())
        assert str((tmp_path / "app.slnx").resolve()) in calls[-1]

    @pytest.mark.parametrize("kind", ["dir", "cs"])
    def test_non_project_target_fails_clearly(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str) -> None:
        (tmp_path / "a.sln").write_text("")
        if kind == "dir":
            (tmp_path / "sub").mkdir()
            name = "sub"
        else:
            (tmp_path / "Foo.cs").write_text("")
            name = "Foo.cs"
        data, calls = self._run(monkeypatch, tmp_path, name)
        assert data["passed"] is False
        assert ".sln, .slnx or .csproj" in data["output"]
        assert all("--list-sdks" in c for c in calls)

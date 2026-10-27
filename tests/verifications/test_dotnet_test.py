"""Tests for the dotnet-test verification plugin.

Covers: fail-open when the .NET SDK isn't installed (including the bare
muxer-with-no-SDK case), fail-open when no .NET project is found, running
``dotnet test`` once per discovered target (discovery itself is covered in
test_dotnet_target.py), .slnx SDK gating, summed pass/fail counts, configured
targets, and a real-subprocess run proving the shared helper import works.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import subprocess
import sys
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


def _make_fake_run(
    calls: list[list[str]],
    version: str = "8.0.100",
    test_results: dict[str, subprocess.CompletedProcess] | None = None,
) -> object:
    """Fake subprocess.run dispatching on the dotnet subcommand; records every call."""

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(cmd)
        if "--list-sdks" in cmd:
            return _completed(0, stdout="8.0.100 [C:\\dotnet\\sdk]\n")
        if "--version" in cmd:
            return _completed(0, stdout=version + "\n")
        if cmd[1] == "test":
            return (test_results or {}).get(cmd[2], _completed(0, stdout="Passed!  - Failed: 0, Passed: 1\n"))
        raise AssertionError(f"unexpected command: {cmd}")

    return fake_run


def _test_calls(calls: list[list[str]]) -> list[list[str]]:
    return [c for c in calls if len(c) > 1 and c[1] == "test"]


class TestMain:
    """End-to-end main() behavior with subprocess entirely mocked."""

    def test_passes_when_dotnet_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load_check_module()
        with patch.object(mod.shutil, "which", return_value=None):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is True
        assert "skipped" in data["output"].lower()
        assert data["detail"]["status"] == "SKIPPED"
        assert data["detail"]["skip_reason"]

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
        assert data["detail"]["status"] == "SKIPPED"
        assert data["detail"]["skip_reason"]

    def test_passes_when_no_test_project_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load_check_module()
        with (
            patch.object(mod.shutil, "which", return_value="dotnet"),
            patch.object(mod.subprocess, "run", return_value=_completed(0, stdout="8.0.100\n")),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is True
        assert "skipped" in data["output"].lower()
        assert data["detail"]["status"] == "SKIPPED"
        assert data["detail"]["skip_reason"]

    def test_maps_dotnet_test_pass_to_passed_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        mod = _load_check_module()
        (tmp_path / "App.Tests.csproj").write_text("")
        target = str(tmp_path / "App.Tests.csproj")
        fake = _make_fake_run([], test_results={target: _completed(0, stdout="Passed!  - Failed: 0, Passed: 3\n")})
        with (
            patch.object(mod.shutil, "which", return_value="dotnet"),
            patch.object(mod.subprocess, "run", side_effect=fake),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is True
        assert data["detail"]["target"] == target
        assert data["detail"]["targets"] == [target]
        assert data["detail"]["passed_count"] == 3

    def test_maps_dotnet_test_fail_to_failed_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        mod = _load_check_module()
        (tmp_path / "App.Tests.csproj").write_text("")
        target = str(tmp_path / "App.Tests.csproj")
        fake = _make_fake_run([], test_results={target: _completed(1, stdout="Failed!  - Failed: 2, Passed: 1\n")})
        with (
            patch.object(mod.shutil, "which", return_value="dotnet"),
            patch.object(mod.subprocess, "run", side_effect=fake),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is False

    def test_runs_every_test_project_when_no_solution(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        mod = _load_check_module()
        (tmp_path / "app").mkdir()
        (tmp_path / "lib").mkdir()
        app_tests = str(tmp_path / "app" / "App.Tests.csproj")
        lib_tests = str(tmp_path / "lib" / "Lib.Tests.csproj")
        (tmp_path / "app" / "App.Tests.csproj").write_text("")
        (tmp_path / "lib" / "Lib.Tests.csproj").write_text("")
        (tmp_path / "app" / "App.csproj").write_text("")
        calls: list[list[str]] = []
        fake = _make_fake_run(
            calls,
            test_results={
                app_tests: _completed(0, stdout="Passed!  - Failed: 0, Passed: 3\n"),
                lib_tests: _completed(0, stdout="Passed!  - Failed: 0, Passed: 4\n"),
            },
        )
        with (
            patch.object(mod.shutil, "which", return_value="dotnet"),
            patch.object(mod.subprocess, "run", side_effect=fake),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert sorted(c[2] for c in _test_calls(calls)) == sorted([app_tests, lib_tests])
        assert sorted(data["detail"]["targets"]) == sorted([app_tests, lib_tests])
        assert "target" not in data["detail"]
        assert data["passed"] is True
        assert data["detail"]["passed_count"] == 7
        assert data["detail"]["failed"] == 0
        assert f"== {app_tests} ==" in data["output"]

    def test_one_failing_project_fails_and_counts_are_summed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        mod = _load_check_module()
        app_tests = str(tmp_path / "App.Tests.csproj")
        lib_tests = str(tmp_path / "Lib.Tests.csproj")
        (tmp_path / "App.Tests.csproj").write_text("")
        (tmp_path / "Lib.Tests.csproj").write_text("")
        fake = _make_fake_run(
            [],
            test_results={
                app_tests: _completed(0, stdout="Passed!  - Failed: 0, Passed: 3\n"),
                lib_tests: _completed(1, stdout="Failed!  - Failed: 2, Passed: 1\n"),
            },
        )
        with (
            patch.object(mod.shutil, "which", return_value="dotnet"),
            patch.object(mod.subprocess, "run", side_effect=fake),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is False
        assert data["detail"]["failed"] == 2
        assert data["detail"]["passed_count"] == 4

    def test_timeout_marks_failed_and_stops_remaining_targets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        mod = _load_check_module()
        (tmp_path / "App.Tests.csproj").write_text("")
        (tmp_path / "Lib.Tests.csproj").write_text("")
        calls: list[list[str]] = []
        base = _make_fake_run(calls)

        def fake(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if len(cmd) > 1 and cmd[1] == "test":
                calls.append(cmd)
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)
            return base(cmd, **kwargs)

        with (
            patch.object(mod.shutil, "which", return_value="dotnet"),
            patch.object(mod.subprocess, "run", side_effect=fake),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is False
        assert "timed out" in data["output"]
        assert len(_test_calls(calls)) == 1

    def test_test_run_timeout_within_budget(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load_check_module()
        (tmp_path / "App.Tests.csproj").write_text("")
        timeouts: list[float] = []
        base = _make_fake_run([])

        def fake(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if len(cmd) > 1 and cmd[1] == "test":
                timeouts.append(kwargs["timeout"])  # type: ignore[arg-type]
            return base(cmd, **kwargs)

        with (
            patch.object(mod.shutil, "which", return_value="dotnet"),
            patch.object(mod.subprocess, "run", side_effect=fake),
        ):
            _run_main(mod, tmp_path, monkeypatch, capsys)
        assert len(timeouts) == 1
        assert timeouts[0] <= 290

    def test_slnx_used_when_sdk_supports_it(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load_check_module()
        (tmp_path / "App.slnx").write_text("")
        calls: list[list[str]] = []
        with (
            patch.object(mod.shutil, "which", return_value="dotnet"),
            patch.object(mod.subprocess, "run", side_effect=_make_fake_run(calls, version="9.0.200")),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert [c[2] for c in _test_calls(calls)] == [str(tmp_path / "App.slnx")]
        assert data["passed"] is True

    def test_slnx_skipped_on_old_sdk_uses_test_csproj(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        mod = _load_check_module()
        (tmp_path / "App.slnx").write_text("")
        (tmp_path / "App.Tests.csproj").write_text("")
        calls: list[list[str]] = []
        with (
            patch.object(mod.shutil, "which", return_value="dotnet"),
            patch.object(mod.subprocess, "run", side_effect=_make_fake_run(calls, version="8.0.100")),
        ):
            _run_main(mod, tmp_path, monkeypatch, capsys)
        assert [c[2] for c in _test_calls(calls)] == [str(tmp_path / "App.Tests.csproj")]

    def test_third_party_projects_ignored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load_check_module()
        (tmp_path / "third_party").mkdir()
        (tmp_path / "third_party" / "Foo.Tests.csproj").write_text("")
        calls: list[list[str]] = []
        with (
            patch.object(mod.shutil, "which", return_value="dotnet"),
            patch.object(mod.subprocess, "run", side_effect=_make_fake_run(calls)),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert _test_calls(calls) == []
        assert data["detail"]["status"] == "SKIPPED"
        assert ".sln/.slnx" in data["output"]


class TestRealSubprocess:
    """Run check.py as a script to prove the shared helper import resolves."""

    def test_skips_when_dotnet_not_on_path(self, tmp_path: Path) -> None:
        env = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "TEMP", "TMP"}}
        env["PATH"] = ""
        proc = subprocess.run(
            [sys.executable, str(CHECK_SCRIPT)],
            input=json.dumps({"project_root": str(tmp_path)}),
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert "dotnet SDK not found" in json.loads(proc.stdout)["output"]


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
        assert data["detail"]["status"] == "SKIPPED"
        assert data["detail"]["skip_reason"]

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
        assert data["detail"]["status"] == "SKIPPED"
        assert data["detail"]["skip_reason"]

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
        assert data["detail"]["status"] == "SKIPPED"
        assert data["detail"]["skip_reason"]

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

    def test_configured_slnx_target_accepted(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        (tmp_path / "app.slnx").write_text("")
        data, calls = self._run(monkeypatch, tmp_path, "app.slnx")
        assert data["passed"] is True
        assert data["detail"]["target"] == str((tmp_path / "app.slnx").resolve())
        assert str((tmp_path / "app.slnx").resolve()) in calls[-1]

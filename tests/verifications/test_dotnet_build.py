"""Tests for the dotnet-build verification plugin.

Covers: fail-open when the .NET SDK is missing (including the bare
``dotnet`` muxer with no SDK registered), fail-open when no
.sln/.slnx/.csproj is present, building every discovered project when no
solution exists, ``.slnx`` gated on SDK >= 9.0.200, excluded dirs, and build
pass/fail mapping to the result's ``passed`` field. Discovery itself is
tested in ``test_dotnet_target.py``.
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


def _sdk_run(version: str, build_rc: dict[str, int] | None = None) -> tuple[object, list[list[str]]]:
    """Build a fake subprocess.run reporting SDK ``version``; records build commands."""
    builds: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if "--list-sdks" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="8.0.100\n")
        if "--version" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=f"{version}\n")
        builds.append(cmd)
        rc = (build_rc or {}).get(cmd[2], 0)
        return subprocess.CompletedProcess(args=cmd, returncode=rc, stdout="out", stderr="")

    return fake_run, builds


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
        assert "No .sln/.slnx/.csproj found" in data["output"]

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
        assert data["detail"]["status"] == "SKIPPED"
        assert data["detail"]["skip_reason"]

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
        assert "No .sln/.slnx/.csproj found" in data["output"]

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
        assert "No .sln/.slnx/.csproj found" in data["output"]

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
        assert "No .sln/.slnx/.csproj found" in data["output"]

    def _run_with(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_run: object, context: dict | None = None
    ) -> dict:
        mod = _load_check_module()
        with (
            patch("shutil.which", return_value="/usr/bin/dotnet"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            return _run_main(monkeypatch, mod, context or {"project_root": str(tmp_path)})

    def test_builds_every_project_when_no_solution(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("a", "b"):
            (tmp_path / name).mkdir()
            (tmp_path / name / f"{name}.csproj").write_text("")
        fake_run, builds = _sdk_run("8.0.100")

        data = self._run_with(monkeypatch, tmp_path, fake_run)

        expected = [str(tmp_path / "a" / "a.csproj"), str(tmp_path / "b" / "b.csproj")]
        assert data["passed"] is True
        assert sorted(c[2] for c in builds) == expected
        assert sorted(data["detail"]["targets"]) == expected
        assert "target" not in data["detail"]

    def test_one_failing_project_fails_overall(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("a", "b"):
            (tmp_path / name).mkdir()
            (tmp_path / name / f"{name}.csproj").write_text("")
        fake_run, builds = _sdk_run("8.0.100", {str(tmp_path / "b" / "b.csproj"): 1})

        data = self._run_with(monkeypatch, tmp_path, fake_run)

        assert data["passed"] is False
        assert len(builds) == 2

    def test_slnx_built_when_sdk_supports_it(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "app.slnx").write_text("")
        fake_run, builds = _sdk_run("9.0.200")

        data = self._run_with(monkeypatch, tmp_path, fake_run)

        assert data["passed"] is True
        assert [c[2] for c in builds] == [str(tmp_path / "app.slnx")]

    def test_slnx_ignored_on_old_sdk_builds_csproj(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "app.slnx").write_text("")
        (tmp_path / "app.csproj").write_text("")
        fake_run, builds = _sdk_run("8.0.100")

        data = self._run_with(monkeypatch, tmp_path, fake_run)

        assert data["passed"] is True
        assert [c[2] for c in builds] == [str(tmp_path / "app.csproj")]

    def test_third_party_projects_ignored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "third_party").mkdir()
        (tmp_path / "third_party" / "lib.csproj").write_text("")
        (tmp_path / "app.csproj").write_text("")
        fake_run, builds = _sdk_run("8.0.100")

        data = self._run_with(monkeypatch, tmp_path, fake_run)

        assert data["passed"] is True
        assert [c[2] for c in builds] == [str(tmp_path / "app.csproj")]

    def test_build_timeout_fails_and_stops_remaining_targets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in ("a", "b"):
            (tmp_path / name).mkdir()
            (tmp_path / name / f"{name}.csproj").write_text("")
        attempted: list[str] = []

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if "--list-sdks" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="8.0.100\n")
            attempted.append(cmd[2])
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)

        data = self._run_with(monkeypatch, tmp_path, fake_run)

        assert data["passed"] is False
        assert "timed out" in data["output"]
        assert len(attempted) == 1

    def test_build_timeout_kwarg_within_budget(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "app.sln").write_text("")
        timeouts: list[float] = []

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if "--list-sdks" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="8.0.100\n")
            timeouts.append(kwargs["timeout"])  # type: ignore[arg-type]
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")

        self._run_with(monkeypatch, tmp_path, fake_run)

        assert len(timeouts) == 1
        assert timeouts[0] <= 110


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

    def test_configured_slnx_accepted(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        (tmp_path / "app.slnx").write_text("")
        data, calls = self._run(monkeypatch, tmp_path, "app.slnx")
        assert data["passed"] is True
        assert str((tmp_path / "app.slnx").resolve()) in calls[-1]


@pytest.mark.parametrize("changed", [".editorconfig", "Directory.Build.props", "global.json", "nuget.config"])
def test_build_affecting_non_cs_file_does_not_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    """Config files that change build results must not trigger the skip rule."""
    mod = _load_check_module()
    with patch("shutil.which", return_value=None):
        data = _run_main(monkeypatch, mod, {"project_root": str(tmp_path), "changed_files": [changed]})
    assert data["detail"].get("status") != "SKIPPED" or "not found" in data["output"].lower()
    assert "No .NET build-affecting files changed" not in data["output"]

"""Tests for the go-test verification plugin.

Covers: per-package coverage parsing on captured ``go test -cover`` output,
the coverage gate over ``config.go.coverage_packages`` globs, command
construction (-race, -tags, -coverprofile), data-race / test-failure
mapping, and skip behavior. Only the go subprocess is mocked; one
integration test runs a tiny temp module when ``go`` is on PATH.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest

if TYPE_CHECKING:
    import types

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "go-test" / "check.py"

# Captured from `go test -race -cover ./...` (Go 1.22), tabs preserved.
FIXTURE_OUTPUT = (
    "ok  \texample.com/m/internal/censor\t0.045s\tcoverage: 62.5% of statements\n"
    "ok  \texample.com/m/internal/store\t(cached)\tcoverage: 91.3% of statements\n"
    "ok  \texample.com/m/internal/util\t0.012s\tcoverage: 10.0% of statements\n"
    "\texample.com/m/cmd/server\t\tcoverage: 0.0% of statements\n"
    "?   \texample.com/m/internal/gen\t[no test files]\n"
    "ok  \texample.com/m\t0.010s\tcoverage: 100.0% of statements\n"
)

DATA_RACE_OUTPUT = (
    "==================\n"
    "WARNING: DATA RACE\n"
    "Write at 0x00c000012345 by goroutine 8:\n"
    "  example.com/m/internal/store.(*Store).Put()\n"
    "==================\n"
    "--- FAIL: TestConcurrentPut (0.00s)\n"
    "    testing.go:1465: race detected during execution of test\n"
    "FAIL\n"
    "coverage: 80.0% of statements\n"
    "FAIL\texample.com/m/internal/store\t0.031s\n"
    "FAIL\n"
)


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("go_test_check", CHECK_SCRIPT)
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
    go_config: dict | None = None,
) -> dict:
    context: dict[str, object] = {"project_root": str(project_root)}
    if changed_files is not None:
        context["changed_files"] = changed_files
    if go_config is not None:
        context["config"] = {"go": go_config}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(context)))
    with contextlib.suppress(SystemExit):
        mod.main()
    return json.loads(capsys.readouterr().out)


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _go_module(root: Path) -> None:
    (root / "go.mod").write_text("module example.com/m\n\ngo 1.22\n")


class TestParseCoverage:
    def test_parses_per_package_coverage(self) -> None:
        assert _load()._parse_coverage(FIXTURE_OUTPUT) == {
            "example.com/m/internal/censor": 62.5,
            "example.com/m/internal/store": 91.3,
            "example.com/m/internal/util": 10.0,
            "example.com/m/cmd/server": 0.0,
            "example.com/m": 100.0,
        }

    def test_bare_coverage_line_ignored(self) -> None:
        assert _load()._parse_coverage("coverage: 80.0% of statements\n") == {}

    def test_failed_package_output_yields_no_bogus_entries(self) -> None:
        assert _load()._parse_coverage(DATA_RACE_OUTPUT) == {}


class TestModulePath:
    def test_reads_module_directive(self, tmp_path: Path) -> None:
        _go_module(tmp_path)
        assert _load()._module_path(tmp_path) == "example.com/m"

    def test_none_without_directive(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("go 1.22\n")
        assert _load()._module_path(tmp_path) is None


COVERAGE = {
    "example.com/m/internal/censor": 62.5,
    "example.com/m/internal/store": 91.3,
    "example.com/m/internal/util": 10.0,
    "example.com/m": 100.0,
}


class TestBelowThreshold:
    def test_gate_off_when_min_zero(self) -> None:
        assert _load()._below_threshold(COVERAGE, "example.com/m", 0.0, []) == []

    def test_package_in_list_below_min_reported(self) -> None:
        result = _load()._below_threshold(COVERAGE, "example.com/m", 80.0, ["internal/censor", "internal/store"])
        assert result == [("internal/censor", 62.5)]

    def test_package_outside_list_ignored(self) -> None:
        result = _load()._below_threshold(COVERAGE, "example.com/m", 80.0, ["internal/store"])
        assert result == []

    def test_glob_patterns(self) -> None:
        result = _load()._below_threshold(COVERAGE, "example.com/m", 80.0, ["internal/*"])
        assert result == [("internal/censor", 62.5), ("internal/util", 10.0)]

    def test_full_import_path_pattern(self) -> None:
        result = _load()._below_threshold(COVERAGE, "example.com/m", 80.0, ["example.com/m/internal/util"])
        assert result == [("internal/util", 10.0)]

    def test_empty_list_means_whole_module(self) -> None:
        result = _load()._below_threshold(COVERAGE, "example.com/m", 80.0, [])
        assert result == [("internal/censor", 62.5), ("internal/util", 10.0)]

    def test_root_package_matches_dot(self) -> None:
        result = _load()._below_threshold({"example.com/m": 5.0}, "example.com/m", 80.0, ["."])
        assert result == [(".", 5.0)]


class TestBuildCommand:
    def test_race_true_includes_race_and_coverprofile(self) -> None:
        cmd = _load()._build_command("go", {}, "cover.out", True)
        assert cmd == ["go", "test", "-race", "-coverprofile=cover.out", "./..."]

    def test_race_off_and_tags(self) -> None:
        cmd = _load()._build_command("go", {"race": False, "test_tags": ["integration"]}, "c.out")
        assert cmd == ["go", "test", "-tags", "integration", "-coverprofile=c.out", "./..."]


class TestRaceEnabled:
    def _resolve(self, race: object, env_out: str, which: str | None, rc: int = 0) -> tuple[bool, str | None]:
        mod = _load()
        with (
            patch.object(mod.subprocess, "run", return_value=_completed(rc, stdout=env_out)),
            patch.object(mod.shutil, "which", return_value=which),
        ):
            return mod._race_enabled("go", race, Path("."))

    def test_auto_with_cgo_and_cc(self) -> None:
        assert self._resolve("auto", "1\ngcc\n", "/usr/bin/gcc") == (True, None)

    def test_auto_cgo_disabled(self) -> None:
        ok, warn = self._resolve("auto", "0\ngcc\n", "/usr/bin/gcc")
        assert ok is False
        assert warn == "-race skipped: cgo/C compiler unavailable"

    def test_auto_cc_missing(self) -> None:
        ok, warn = self._resolve("auto", "1\ngcc\n", None)
        assert ok is False
        assert warn is not None

    def test_auto_go_env_fails(self) -> None:
        assert self._resolve("auto", "", None, rc=1)[0] is False

    def test_true_is_strict_and_false_never(self) -> None:
        assert self._resolve(True, "0\n\n", None) == (True, None)
        assert self._resolve(False, "1\ngcc\n", "gcc") == (False, None)


class TestMain:
    def test_skips_when_no_go_files_changed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        mock_run = Mock(side_effect=AssertionError("subprocess.run should not be called"))
        with patch.object(mod.subprocess, "run", mock_run):
            data = _run_main(mod, tmp_path, monkeypatch, capsys, changed_files=["README.md", "src/app.py"])
        mock_run.assert_not_called()
        assert data["passed"] is True
        assert "no relevant files changed" in data["output"].lower()

    def test_skips_when_go_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        _go_module(tmp_path)
        with patch.object(mod.shutil, "which", return_value=None):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is True
        assert "skipped" in data["output"].lower()

    def test_skips_when_no_go_mod(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        with patch.object(mod.shutil, "which", return_value="go"):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is True
        assert "go.mod" in data["output"]

    def test_coverage_below_min_fails_naming_package_and_pct(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        mod = _load()
        _go_module(tmp_path)
        cfg = {"coverage_min": 80, "coverage_packages": ["internal/censor", "internal/store"]}
        with (
            patch.object(mod.shutil, "which", return_value="go"),
            patch.object(mod.subprocess, "run", return_value=_completed(0, stdout=FIXTURE_OUTPUT)),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys, changed_files=["main.go"], go_config=cfg)
        assert data["passed"] is False
        assert "internal/censor" in data["output"]
        assert "62.5%" in data["output"]
        assert data["detail"]["below_threshold"] == {"internal/censor": 62.5}

    def test_package_outside_list_below_min_does_not_fail(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        mod = _load()
        _go_module(tmp_path)
        cfg = {"coverage_min": 80, "coverage_packages": ["internal/store"]}
        with (
            patch.object(mod.shutil, "which", return_value="go"),
            patch.object(mod.subprocess, "run", return_value=_completed(0, stdout=FIXTURE_OUTPUT)),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys, go_config=cfg)
        assert data["passed"] is True
        assert data["detail"]["coverage"]["example.com/m/internal/util"] == 10.0

    def test_data_race_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        _go_module(tmp_path)
        run = Mock(return_value=_completed(1, stdout=DATA_RACE_OUTPUT))
        with patch.object(mod.shutil, "which", return_value="go"), patch.object(mod.subprocess, "run", run):
            data = _run_main(mod, tmp_path, monkeypatch, capsys, go_config={"race": True})
        assert data["passed"] is False
        assert "DATA RACE" in data["output"]
        assert "-race" in run.call_args.args[0]

    def test_auto_default_without_cgo_warns_and_drops_race(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        mod = _load()
        _go_module(tmp_path)
        run = Mock(side_effect=[_completed(0, stdout="0\ngcc\n"), _completed(0, stdout=FIXTURE_OUTPUT)])
        with patch.object(mod.shutil, "which", return_value="go"), patch.object(mod.subprocess, "run", run):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert "-race" not in run.call_args.args[0]
        assert data["detail"]["warnings"] == ["-race skipped: cgo/C compiler unavailable"]
        assert "-race skipped" in data["output"]

    def test_auto_default_with_cgo_adds_race(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        _go_module(tmp_path)
        run = Mock(side_effect=[_completed(0, stdout="1\ngcc\n"), _completed(0, stdout=FIXTURE_OUTPUT)])
        with patch.object(mod.shutil, "which", return_value="go"), patch.object(mod.subprocess, "run", run):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert "-race" in run.call_args.args[0]
        assert data["detail"]["warnings"] == []

    def test_no_config_runs_without_gate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        _go_module(tmp_path)
        with (
            patch.object(mod.shutil, "which", return_value="go"),
            patch.object(mod.subprocess, "run", return_value=_completed(0, stdout=FIXTURE_OUTPUT)),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is True


@pytest.mark.skipif(shutil.which("go") is None, reason="go toolchain not on PATH")
def test_integration_tiny_module_coverage_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """Real `go test` on a temp module: an untested function in a gated package fails the gate."""
    mod = _load()
    _go_module(tmp_path)
    pkg = tmp_path / "internal" / "calc"
    pkg.mkdir(parents=True)
    (pkg / "calc.go").write_text(
        "package calc\n\nfunc Add(a, b int) int { return a + b }\n\nfunc Sub(a, b int) int { return a - b }\n"
    )
    (pkg / "calc_test.go").write_text(
        'package calc\n\nimport "testing"\n\n'
        'func TestAdd(t *testing.T) {\n\tif Add(1, 2) != 3 {\n\t\tt.Fatal("bad")\n\t}\n}\n'
    )
    cfg = {"coverage_min": 80, "coverage_packages": ["internal/calc"], "race": False}
    data = _run_main(mod, tmp_path, monkeypatch, capsys, go_config=cfg)
    assert data["passed"] is False
    assert "internal/calc" in data["output"]
    assert "50.0%" in data["output"]


def test_timeout_fails_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    mod = _load()
    _go_module(tmp_path)
    with (
        patch.object(mod.shutil, "which", return_value="go"),
        patch.object(mod.subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="go", timeout=590)),
    ):
        data = _run_main(mod, tmp_path, monkeypatch, capsys)
    assert data["passed"] is False
    assert "timed out" in data["output"]


_PROFILE = (
    "mode: atomic\n"
    "example.com/m/a/a.go:3.10,5.2 3 1\n"
    "example.com/m/a/a.go:7.10,9.2 1 0\n"
    "example.com/m/b/b.go:3.10,5.2 4 0\n"
    "example.com/m/b/b.go:3.10,5.2 4 2\n"
)


class TestTotalCoverage:
    def test_statement_weighted_with_duplicate_blocks_merged(self) -> None:
        # covered stmts: a(3) + b(4, duplicate block counts merged) = 7 of 8
        assert _load()._total_coverage(_PROFILE) == pytest.approx(87.5)

    def test_none_for_empty_profile(self) -> None:
        assert _load()._total_coverage("mode: set\n") is None


class TestSummary:
    def test_counts_and_total(self) -> None:
        out = "ok  \texample.com/m/a\t0.1s\tcoverage: 80.0% of statements\nFAIL\texample.com/m/b\t0.2s\nFAIL\n"
        assert _load()._summary(out, 72.25) == "1 package(s) ok, 1 FAIL, total coverage 72.2%"

    def test_without_total(self) -> None:
        assert _load()._summary("ok  \texample.com/m/a\t0.1s\n", None) == "1 package(s) ok, 0 FAIL"


def test_main_reports_summary_with_total_from_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    mod = _load()
    _go_module(tmp_path)

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess:
        profile = next(a for a in cmd if a.startswith("-coverprofile=")).split("=", 1)[1]
        Path(profile).write_text(_PROFILE, encoding="utf-8")
        return _completed(0, stdout="ok  \texample.com/m/a\t0.1s\tcoverage: 75.0% of statements\n")

    with patch.object(mod.shutil, "which", return_value="go"), patch.object(mod.subprocess, "run", fake_run):
        data = _run_main(mod, tmp_path, monkeypatch, capsys, go_config={"race": False})
    assert data["detail"]["coverage_total"] == pytest.approx(87.5)
    assert data["detail"]["summary"] == "1 package(s) ok, 0 FAIL, total coverage 87.5%"

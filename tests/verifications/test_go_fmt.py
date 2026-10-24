"""Tests for the go-fmt verification plugin.

Covers: skip when no Go-relevant files changed, fail-open when the go
toolchain or go.mod is missing, gofmt target selection (vendor/ and hidden
dirs excluded), and failure listing unformatted files. The gofmt
subprocess is the only thing mocked; one integration test runs the real
toolchain when ``go`` is on PATH.
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

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "go-fmt" / "check.py"


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("go_fmt_check", CHECK_SCRIPT)
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
    auto_fix: bool = False,
) -> dict:
    context: dict[str, object] = {"project_root": str(project_root)}
    if auto_fix:
        context["auto_fix"] = True
    if changed_files is not None:
        context["changed_files"] = changed_files
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(context)))
    with contextlib.suppress(SystemExit):
        mod.main()
    return json.loads(capsys.readouterr().out)


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _go_module(root: Path) -> None:
    (root / "go.mod").write_text("module example.com/m\n\ngo 1.22\n")


class TestIsGoRelevant:
    @pytest.mark.parametrize(
        "path", ["main.go", "internal/x/y_test.go", "go.mod", "go.sum", "sub/go.mod", "vendor/modules.txt", "A.GO"]
    )
    def test_relevant(self, path: str) -> None:
        assert _load()._is_go_relevant(path) is True

    @pytest.mark.parametrize("path", ["README.md", "src/app.py", "go.mod.bak", "docs/vendor.md"])
    def test_not_relevant(self, path: str) -> None:
        assert _load()._is_go_relevant(path) is False


class TestFormatTargets:
    def test_excludes_vendor_and_hidden_dirs(self, tmp_path: Path) -> None:
        mod = _load()
        for d in ["vendor", ".git", ".ydk", "node_modules", "internal", "cmd"]:
            (tmp_path / d).mkdir()
        (tmp_path / "main.go").write_text("package main\n")
        (tmp_path / "README.md").write_text("")
        assert mod._format_targets(tmp_path) == ["cmd", "internal", "main.go"]


class TestMain:
    def test_skips_when_no_go_files_changed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        mock_run = Mock(side_effect=AssertionError("subprocess.run should not be called"))
        with patch.object(mod.subprocess, "run", mock_run):
            data = _run_main(mod, tmp_path, monkeypatch, capsys, changed_files=["README.md"])
        mock_run.assert_not_called()
        assert data["passed"] is True
        assert "no relevant files changed" in data["output"].lower()

    def test_skips_when_go_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        _go_module(tmp_path)
        with patch.object(mod.shutil, "which", return_value=None):
            data = _run_main(mod, tmp_path, monkeypatch, capsys, changed_files=["main.go"])
        assert data["passed"] is True
        assert "skipped" in data["output"].lower()
        assert data["detail"]["status"] == "SKIPPED"
        assert data["detail"]["skip_reason"] == data["output"]

    def test_skips_when_no_go_mod(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        with patch.object(mod.shutil, "which", return_value="gofmt"):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is True
        assert "go.mod" in data["output"]

    def test_unformatted_file_fails_listing_it(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        _go_module(tmp_path)
        (tmp_path / "main.go").write_text("package main\n")
        run = Mock(return_value=_completed(0, stdout="main.go\ninternal/x/bad.go\n"))
        with patch.object(mod.shutil, "which", return_value="gofmt"), patch.object(mod.subprocess, "run", run):
            data = _run_main(mod, tmp_path, monkeypatch, capsys, changed_files=["main.go"])
        assert data["passed"] is False
        assert "main.go" in data["output"]
        assert "internal/x/bad.go" in data["output"]
        assert data["detail"]["files"] == ["main.go", "internal/x/bad.go"]
        assert run.call_args.args[0][:2] == ["gofmt", "-l"]

    def test_clean_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        _go_module(tmp_path)
        (tmp_path / "main.go").write_text("package main\n")
        with (
            patch.object(mod.shutil, "which", return_value="gofmt"),
            patch.object(mod.subprocess, "run", return_value=_completed(0)),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is True

    def test_gofmt_error_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        _go_module(tmp_path)
        (tmp_path / "main.go").write_text("package main\n")
        with (
            patch.object(mod.shutil, "which", return_value="gofmt"),
            patch.object(mod.subprocess, "run", return_value=_completed(2, stderr="main.go:1:1: expected 'package'")),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is False
        assert "expected 'package'" in data["output"]


@pytest.mark.skipif(shutil.which("go") is None, reason="go toolchain not on PATH")
def test_integration_real_gofmt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    mod = _load()
    _go_module(tmp_path)
    (tmp_path / "main.go").write_text("package main\nfunc main( ) {  }\n")
    data = _run_main(mod, tmp_path, monkeypatch, capsys)
    assert data["passed"] is False
    assert "main.go" in data["output"]


@pytest.mark.parametrize("name", ["go-fmt", "go-vet", "go-test", "go-vendor"])
def test_go_plugin_manifests_require_go(name: str) -> None:
    import yaml

    manifest = yaml.safe_load((CHECK_SCRIPT.parents[1] / name / "manifest.yaml").read_text())
    assert manifest["name"] == name
    assert manifest["requires"] == ["go"]


def test_go_quality_catalog_item() -> None:
    import yaml

    catalog = yaml.safe_load((CHECK_SCRIPT.parents[2] / "catalog" / "go-quality" / "catalog.yaml").read_text())
    assert catalog["name"] == "go-quality"
    assert "go" in catalog["tags"]


def test_timeout_fails_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    mod = _load()
    _go_module(tmp_path)
    with (
        patch.object(mod.shutil, "which", return_value="gofmt"),
        patch.object(mod.subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="gofmt", timeout=55)),
    ):
        data = _run_main(mod, tmp_path, monkeypatch, capsys)
    assert data["passed"] is False
    assert "timed out" in data["output"]


def test_nested_vendor_and_testdata_files_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    mod = _load()
    _go_module(tmp_path)
    out = "internal/x/vendor/a.go\ninternal/y/testdata/b.go\n"
    with (
        patch.object(mod.shutil, "which", return_value="gofmt"),
        patch.object(mod.subprocess, "run", return_value=_completed(0, stdout=out)),
    ):
        data = _run_main(mod, tmp_path, monkeypatch, capsys)
    assert data["passed"] is True


def test_auto_fix_runs_gofmt_w_on_flagged_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    mod = _load()
    _go_module(tmp_path)
    run = Mock(side_effect=[_completed(0, stdout="main.go\ninternal/x/bad.go\n"), _completed(0)])
    with patch.object(mod.shutil, "which", return_value="gofmt"), patch.object(mod.subprocess, "run", run):
        data = _run_main(mod, tmp_path, monkeypatch, capsys, auto_fix=True)
    assert run.call_args_list[1].args[0] == ["gofmt", "-w", "main.go", "internal/x/bad.go"]
    assert data["passed"] is True
    assert data["detail"]["auto_fixed_count"] == 2
    assert "internal/x/bad.go" in data["output"]


def test_auto_fix_write_failure_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    mod = _load()
    _go_module(tmp_path)
    run = Mock(side_effect=[_completed(0, stdout="main.go\n"), _completed(2, stderr="permission denied")])
    with patch.object(mod.shutil, "which", return_value="gofmt"), patch.object(mod.subprocess, "run", run):
        data = _run_main(mod, tmp_path, monkeypatch, capsys, auto_fix=True)
    assert data["passed"] is False
    assert "permission denied" in data["output"]


def test_go_fmt_manifest_supports_auto_fix() -> None:
    import yaml

    manifest = yaml.safe_load((CHECK_SCRIPT.parent / "manifest.yaml").read_text())
    assert manifest["supports_auto_fix"] is True


def test_auto_fix_only_rewrites_changed_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    mod = _load()
    _go_module(tmp_path)
    run = Mock(side_effect=[_completed(0, stdout="main.go\ninternal/x/bad.go\n"), _completed(0)])
    with patch.object(mod.shutil, "which", return_value="gofmt"), patch.object(mod.subprocess, "run", run):
        data = _run_main(mod, tmp_path, monkeypatch, capsys, changed_files=["main.go"], auto_fix=True)
    assert run.call_args_list[1].args[0] == ["gofmt", "-w", "main.go"]
    assert data["passed"] is False
    assert data["detail"] == {"files": ["internal/x/bad.go"], "auto_fixed_count": 1}

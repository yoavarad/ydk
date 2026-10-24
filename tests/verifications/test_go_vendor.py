"""Tests for the go-vendor verification plugin.

Covers: vendor-tree comparison, skip behavior (no Go files changed, no go,
no go.mod, no vendor/), stale vendor/ detection via ``go mod vendor -o``
into a temp dir, and ``go build -mod=vendor`` failure mapping. Only the go
subprocess is mocked: the fake writes a regenerated tree into the ``-o``
directory just as the real toolchain would.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

if TYPE_CHECKING:
    import types

    import pytest

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "go-vendor" / "check.py"


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("go_vendor_check", CHECK_SCRIPT)
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
    context: dict[str, object] = {"project_root": str(project_root)}
    if changed_files is not None:
        context["changed_files"] = changed_files
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(context)))
    with contextlib.suppress(SystemExit):
        mod.main()
    return json.loads(capsys.readouterr().out)


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


VENDOR = {"modules.txt": "# golang.org/x/text v0.14.0\n", "golang.org/x/text/doc.go": "package text\n"}


def _project(root: Path) -> None:
    (root / "go.mod").write_text("module example.com/m\n\ngo 1.22\n")
    _write_tree(root / "vendor", VENDOR)


def _fake_go(regenerated: dict[str, str], build: subprocess.CompletedProcess | None = None) -> Mock:
    """Fake the go subprocess: `mod vendor -o DIR` writes `regenerated` into DIR; `build` returns `build`."""

    def run(cmd: list[str], **_kw: object) -> subprocess.CompletedProcess:
        if cmd[1:3] == ["mod", "vendor"]:
            _write_tree(Path(cmd[cmd.index("-o") + 1]), regenerated)
            return _completed(0)
        return build or _completed(0)

    return Mock(side_effect=run)


class TestDiffTrees:
    def test_identical_trees(self, tmp_path: Path) -> None:
        _write_tree(tmp_path / "a", VENDOR)
        _write_tree(tmp_path / "b", VENDOR)
        assert _load()._diff_trees(tmp_path / "a", tmp_path / "b") == []

    def test_reports_changed_added_removed(self, tmp_path: Path) -> None:
        _write_tree(tmp_path / "a", {"same.go": "x", "changed.go": "old", "removed.go": "r"})
        _write_tree(tmp_path / "b", {"same.go": "x", "changed.go": "new", "sub/added.go": "a"})
        assert _load()._diff_trees(tmp_path / "a", tmp_path / "b") == ["changed.go", "removed.go", "sub/added.go"]


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
        _project(tmp_path)
        with patch.object(mod.shutil, "which", return_value=None):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is True
        assert "skipped" in data["output"].lower()
        assert data["detail"]["status"] == "SKIPPED"
        assert data["detail"]["skip_reason"] == data["output"]

    def test_skips_when_no_vendor_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        (tmp_path / "go.mod").write_text("module example.com/m\n")
        with patch.object(mod.shutil, "which", return_value="go"):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is True
        assert "vendor/" in data["output"]

    def test_stale_vendor_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        _project(tmp_path)
        regenerated = {**VENDOR, "modules.txt": "# golang.org/x/text v0.15.0\n"}
        with (
            patch.object(mod.shutil, "which", return_value="go"),
            patch.object(mod.subprocess, "run", _fake_go(regenerated)),
        ):
            data = _run_main(mod, tmp_path, monkeypatch, capsys, changed_files=["go.mod"])
        assert data["passed"] is False
        assert "stale" in data["output"].lower()
        assert "modules.txt" in data["output"]
        assert data["detail"]["stale_files"] == ["modules.txt"]

    def test_fresh_vendor_and_build_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        _project(tmp_path)
        fake = _fake_go(VENDOR)
        with patch.object(mod.shutil, "which", return_value="go"), patch.object(mod.subprocess, "run", fake):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is True
        assert fake.call_args.args[0] == ["go", "build", "-mod=vendor", "./..."]
        assert (tmp_path / "vendor" / "modules.txt").read_text() == VENDOR["modules.txt"]

    def test_vendor_build_failure_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        _project(tmp_path)
        fake = _fake_go(VENDOR, build=_completed(1, stderr="cannot find module providing package x"))
        with patch.object(mod.shutil, "which", return_value="go"), patch.object(mod.subprocess, "run", fake):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is False
        assert "cannot find module" in data["output"]

    def test_go_mod_vendor_error_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        _project(tmp_path)
        run = Mock(return_value=_completed(1, stderr="go: updates to go.mod needed"))
        with patch.object(mod.shutil, "which", return_value="go"), patch.object(mod.subprocess, "run", run):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is False
        assert "updates to go.mod needed" in data["output"]


def test_timeout_fails_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    mod = _load()
    _project(tmp_path)
    with (
        patch.object(mod.shutil, "which", return_value="go"),
        patch.object(mod.subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="go", timeout=140)),
    ):
        data = _run_main(mod, tmp_path, monkeypatch, capsys)
    assert data["passed"] is False
    assert "timed out" in data["output"]


def test_crlf_checkout_not_reported_stale(tmp_path: Path) -> None:
    """core.autocrlf checkouts must not make every vendored file look stale."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "x.go").write_bytes(b"package x\r\n")
    (tmp_path / "b" / "x.go").write_bytes(b"package x\n")
    assert _load()._diff_trees(tmp_path / "a", tmp_path / "b") == []

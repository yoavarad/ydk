"""Tests for the go-vet verification plugin.

Covers: skip when no Go-relevant files changed, fail-open when the go
toolchain or go.mod is missing, build-tag plumbing from
``config.go.test_tags``, and pass/fail mapping from ``go vet``'s exit code.
Only the go subprocess is mocked.
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

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "go-vet" / "check.py"


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("go_vet_check", CHECK_SCRIPT)
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
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is True
        assert "skipped" in data["output"].lower()
        assert data["detail"]["status"] == "SKIPPED"
        assert data["detail"]["skip_reason"] == data["output"]

    def test_skips_when_no_go_mod(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        with patch.object(mod.shutil, "which", return_value="go"):
            data = _run_main(mod, tmp_path, monkeypatch, capsys)
        assert data["passed"] is True
        assert "go.mod" in data["output"]

    def test_vet_failure_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        _go_module(tmp_path)
        run = Mock(return_value=_completed(1, stderr="./main.go:5:2: fmt.Printf format %d has arg of wrong type"))
        with patch.object(mod.shutil, "which", return_value="go"), patch.object(mod.subprocess, "run", run):
            data = _run_main(mod, tmp_path, monkeypatch, capsys, changed_files=["main.go"])
        assert data["passed"] is False
        assert "wrong type" in data["output"]
        assert run.call_args.args[0] == ["go", "vet", "./..."]

    def test_vet_clean_passes_and_forwards_tags(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mod = _load()
        _go_module(tmp_path)
        run = Mock(return_value=_completed(0))
        with patch.object(mod.shutil, "which", return_value="go"), patch.object(mod.subprocess, "run", run):
            data = _run_main(mod, tmp_path, monkeypatch, capsys, go_config={"test_tags": ["integration", "e2e"]})
        assert data["passed"] is True
        assert run.call_args.args[0] == ["go", "vet", "-tags", "integration,e2e", "./..."]


def test_timeout_fails_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    mod = _load()
    _go_module(tmp_path)
    with (
        patch.object(mod.shutil, "which", return_value="go"),
        patch.object(mod.subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="go", timeout=170)),
    ):
        data = _run_main(mod, tmp_path, monkeypatch, capsys)
    assert data["passed"] is False
    assert "timed out" in data["output"]

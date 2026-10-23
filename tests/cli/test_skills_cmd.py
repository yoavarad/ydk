"""Tests for `ydk skills` — always against a tmp CLAUDE_CONFIG_DIR."""

from __future__ import annotations

import importlib.metadata
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from ydk.cli import app
from ydk.core.skills_sync import STAMP_FILE

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

runner = CliRunner()


def _cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    return cfg


def test_sync_installs_bundled_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _cfg(tmp_path, monkeypatch)
    result = runner.invoke(app, ["skills", "sync"])
    assert result.exit_code == 0, result.output
    version = importlib.metadata.version("ydk")
    assert (cfg / "skills" / "ydk" / "SKILL.md").is_file()
    assert (cfg / "skills" / "ydk" / STAMP_FILE).read_text().strip() == version
    assert (cfg / "agents" / "ydk-orchestrator.md").is_file()
    assert not list(cfg.rglob("__pycache__"))


def test_sync_dry_run_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _cfg(tmp_path, monkeypatch)
    result = runner.invoke(app, ["skills", "sync", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "ydk" in result.output
    assert not cfg.exists()


def test_sync_fails_when_no_bundled_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _cfg(tmp_path, monkeypatch)
    monkeypatch.setattr("ydk.cli.skills_cmd.bundled_skills_dir", lambda: tmp_path / "missing")
    result = runner.invoke(app, ["skills", "sync"])
    assert result.exit_code == 1


def test_status_reports_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _cfg(tmp_path, monkeypatch)
    runner.invoke(app, ["skills", "sync"])
    (cfg / "skills" / "ydk" / STAMP_FILE).write_text("0.0.1\n")
    result = runner.invoke(app, ["skills", "status"])
    assert result.exit_code == 0, result.output
    assert "0.0.1" in result.output
    assert "drift" in result.output.lower()


def test_status_reports_not_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _cfg(tmp_path, monkeypatch)
    result = runner.invoke(app, ["skills", "status"])
    assert result.exit_code == 0, result.output
    assert "not installed" in result.output.lower()

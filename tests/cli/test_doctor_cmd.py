"""Tests for ydk doctor CLI command."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from ydk.cli import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def test_doctor_exits_zero_in_valid_project(tmp_path: Path, monkeypatch: object) -> None:
    """ydk doctor exits 0 when all required checks pass."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    config_dir = tmp_path / ".ydk"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("project:\n  name: test-project\n")
    (tmp_path / "docs" / "specs").mkdir(parents=True)
    (tmp_path / "docs" / "adrs").mkdir(parents=True)
    (tmp_path / "docs" / "project-rules.md").write_text("# Rules\n")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0


def test_doctor_shows_check_results(tmp_path: Path, monkeypatch: object) -> None:
    """ydk doctor output includes check names."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    config_dir = tmp_path / ".ydk"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("project:\n  name: test-project\n")
    result = runner.invoke(app, ["doctor"])
    assert "Python" in result.output
    assert "Git" in result.output
    assert "passed" in result.output

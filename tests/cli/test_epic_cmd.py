"""Tests for ydk task create-epic."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from typer.testing import CliRunner

from ydk.cli import app
from ydk.core.config import DEFAULT_CONFIG

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _setup(tmp_path: Path) -> None:
    """Write valid config and manifest for epic creation."""
    d = tmp_path / ".ydk"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.yaml").write_text(yaml.dump(DEFAULT_CONFIG, default_flow_style=False))
    manifest = {
        "last_task_id": 0,
        "last_story_id": 0,
        "last_epic_id": 0,
        "epics": {},
        "stories": {},
        "tasks": {},
    }
    (d / "manifest.yaml").write_text(yaml.dump(manifest, default_flow_style=False))


def test_task_create_epic(tmp_path: Path, monkeypatch: object) -> None:
    """ydk task create-epic creates an epic and exits 0."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup(tmp_path)
    r = runner.invoke(app, ["task", "create-epic", "--title", "Auth"])
    assert r.exit_code == 0
    assert "E-" in r.output

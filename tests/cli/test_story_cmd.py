"""Tests for odk task create-story."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from typer.testing import CliRunner

from odk.cli import app
from odk.core.config import DEFAULT_CONFIG

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _setup(tmp_path: Path) -> None:
    """Write valid config and manifest for story creation."""
    d = tmp_path / ".odk"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.yaml").write_text(yaml.dump(DEFAULT_CONFIG, default_flow_style=False))
    manifest = {
        "last_task_id": 0,
        "last_story_id": 0,
        "last_epic_id": 0,
        "epics": {"E-001": {"title": "Auth", "status": "open", "stories": []}},
        "stories": {},
        "tasks": {},
    }
    (d / "manifest.yaml").write_text(yaml.dump(manifest, default_flow_style=False))


def test_task_create_story(tmp_path: Path, monkeypatch: object) -> None:
    """odk task create-story creates a story and exits 0."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup(tmp_path)
    r = runner.invoke(app, ["task", "create-story", "--title", "Login", "--epic", "E-001"])
    assert r.exit_code == 0
    assert "S-" in r.output

"""Tests for ydk config commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from typer.testing import CliRunner

from ydk.cli import app
from ydk.core.config import DEFAULT_CONFIG

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _write_config(tmp_path: Path) -> Path:
    """Write a valid default config and return its path."""
    config_path = tmp_path / ".ydk" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.dump(DEFAULT_CONFIG, default_flow_style=False))
    return config_path


def test_config_show_exits_0(tmp_path: Path, monkeypatch: object) -> None:
    """ydk config show exits 0 when config exists."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _write_config(tmp_path)
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "my-project" in result.output


def test_config_get_returns_value(tmp_path: Path, monkeypatch: object) -> None:
    """ydk config get spec_check.model prints the model name."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _write_config(tmp_path)
    result = runner.invoke(app, ["config", "get", "spec_check.model"])
    assert result.exit_code == 0
    assert "claude-sonnet" in result.output


def test_config_get_missing_key(tmp_path: Path, monkeypatch: object) -> None:
    """ydk config get with missing key exits non-zero."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _write_config(tmp_path)
    result = runner.invoke(app, ["config", "get", "nonexistent.key"])
    assert result.exit_code != 0
    assert "Key not found" in result.output


def test_config_set_updates_value(tmp_path: Path, monkeypatch: object) -> None:
    """ydk config set spec_check.timeout 90 updates the value."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _write_config(tmp_path)
    result = runner.invoke(app, ["config", "set", "spec_check.timeout", "90"])
    assert result.exit_code == 0
    assert "spec_check.timeout = 90" in result.output

    # Verify it was actually written
    raw = yaml.safe_load((tmp_path / ".ydk" / "config.yaml").read_text())
    assert raw["spec_check"]["timeout"] == 90


def test_config_validate_ok(tmp_path: Path, monkeypatch: object) -> None:
    """ydk config validate exits 0 for valid config."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _write_config(tmp_path)
    result = runner.invoke(app, ["config", "validate"])
    assert result.exit_code == 0
    assert "valid" in result.output.lower()


def test_config_validate_missing(tmp_path: Path, monkeypatch: object) -> None:
    """ydk config validate exits non-zero for missing config."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["config", "validate"])
    assert result.exit_code != 0
    assert "no config found" in result.output.lower()

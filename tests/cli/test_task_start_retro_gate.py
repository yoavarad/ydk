"""Tests for the retro gate on `ydk task start` (task 222)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import yaml
from typer.testing import CliRunner

from ydk.cli import app
from ydk.models.pm import EpicCreate
from ydk.repositories.local.epics import LocalEpicRepository

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _setup_project(tmp_path: Path) -> None:
    (tmp_path / ".ydk").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ydk" / "todos.yaml").write_text("todos: []")


def _make_finished_epic(tmp_path: Path) -> str:
    repo = LocalEpicRepository(tmp_path / ".ydk")
    detail = repo.create_epic(EpicCreate(title="Epic One"))
    repo.update_status(detail.id, "done")
    return detail.id


@patch("ydk.cli.task_cmd._build_lifecycle")
def test_no_finished_epics_proceeds(mock_build: MagicMock, tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_project(tmp_path)
    lc = MagicMock()
    lc.start.return_value = {"worktree": ".ydk/worktrees/T-001"}
    mock_build.return_value = lc

    result = runner.invoke(app, ["task", "start", "T-001"])
    assert result.exit_code == 0
    lc.start.assert_called_once()


@patch("ydk.cli.task_cmd._build_lifecycle")
def test_finished_epic_with_retro_proceeds(mock_build: MagicMock, tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_project(tmp_path)
    epic_id = _make_finished_epic(tmp_path)
    retros_dir = tmp_path / ".ydk" / "retros"
    retros_dir.mkdir(parents=True)
    (retros_dir / f"{epic_id}.md").write_text("# Retro", encoding="utf-8")
    lc = MagicMock()
    lc.start.return_value = {"worktree": ".ydk/worktrees/T-001"}
    mock_build.return_value = lc

    result = runner.invoke(app, ["task", "start", "T-001"])
    assert result.exit_code == 0
    lc.start.assert_called_once()


@patch("ydk.cli.task_cmd._build_lifecycle")
def test_finished_epic_without_retro_refuses(mock_build: MagicMock, tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_project(tmp_path)
    epic_id = _make_finished_epic(tmp_path)
    lc = MagicMock()
    mock_build.return_value = lc

    result = runner.invoke(app, ["task", "start", "T-001"])
    assert result.exit_code == 1
    assert epic_id in result.output
    assert "ydk memory retrospective --epic" in result.output
    lc.start.assert_not_called()


@patch("ydk.cli.task_cmd._build_lifecycle")
def test_skip_retro_check_flag_bypasses(mock_build: MagicMock, tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_project(tmp_path)
    _make_finished_epic(tmp_path)
    lc = MagicMock()
    lc.start.return_value = {"worktree": ".ydk/worktrees/T-001"}
    mock_build.return_value = lc

    result = runner.invoke(app, ["task", "start", "T-001", "--skip-retro-check"])
    assert result.exit_code == 0
    lc.start.assert_called_once()


@patch("ydk.cli.task_cmd._get_epic_repo")
@patch("ydk.cli.task_cmd._build_lifecycle")
def test_epic_repo_error_warns_and_proceeds(
    mock_build: MagicMock, mock_get_epic_repo: MagicMock, tmp_path: Path, monkeypatch: object
) -> None:
    """A broken epic repository must not block `task start` project-wide."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_project(tmp_path)
    mock_get_epic_repo.side_effect = RuntimeError("boom")
    lc = MagicMock()
    lc.start.return_value = {"worktree": ".ydk/worktrees/T-001"}
    mock_build.return_value = lc

    result = runner.invoke(app, ["task", "start", "T-001"])
    assert result.exit_code == 0
    assert "Warning" in result.output
    lc.start.assert_called_once()


@patch("ydk.cli.task_cmd._build_lifecycle")
def test_config_opt_out_bypasses(mock_build: MagicMock, tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_project(tmp_path)
    (tmp_path / ".ydk" / "config.yaml").write_text(
        yaml.dump({"project": {"name": "x"}, "learning": {"require_epic_retro": False}})
    )
    _make_finished_epic(tmp_path)
    lc = MagicMock()
    lc.start.return_value = {"worktree": ".ydk/worktrees/T-001"}
    mock_build.return_value = lc

    result = runner.invoke(app, ["task", "start", "T-001"])
    assert result.exit_code == 0
    lc.start.assert_called_once()

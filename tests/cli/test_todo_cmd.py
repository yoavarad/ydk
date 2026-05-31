"""Tests for odk.cli.todo_cmd — CLI layer for TODO management."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path
from typer.testing import CliRunner

from odk.cli import app

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Create a minimal project structure with a TODO registry."""
    (tmp_path / ".odk").mkdir()
    return tmp_path


def _run(*args: str, cwd: Path | None = None) -> object:
    """Invoke the CLI, optionally chdir'ing first."""
    if cwd is not None:
        with patch("odk.cli.todo_cmd.Path") as mock_path:
            mock_path.cwd.return_value = cwd
            return runner.invoke(app, list(args))
    return runner.invoke(app, list(args))


# --- list ---


def test_list_empty(project: Path) -> None:
    with patch("odk.cli.todo_cmd.Path") as mock_path:
        mock_path.cwd.return_value = project
        result = runner.invoke(app, ["todo", "list"])
    assert result.exit_code == 0
    assert "No TODOs found" in result.output


def test_list_with_items(project: Path) -> None:
    from odk.core.todo_manager import TodoManager

    mgr = TodoManager(project)
    mgr.register(file="a.py", line=1, method="A.x", description="First")
    mgr.register(file="b.py", line=2, method="B.y", description="Second")

    with patch("odk.cli.todo_cmd.Path") as mock_path:
        mock_path.cwd.return_value = project
        result = runner.invoke(app, ["todo", "list"])
    assert result.exit_code == 0
    assert "ODK-TODO-001" in result.output
    assert "ODK-TODO-002" in result.output


def test_list_json_format(project: Path) -> None:
    from odk.core.todo_manager import TodoManager

    mgr = TodoManager(project)
    mgr.register(file="a.py", line=1, method="A.x")

    with patch("odk.cli.todo_cmd.Path") as mock_path:
        mock_path.cwd.return_value = project
        result = runner.invoke(app, ["--format", "json", "todo", "list"])
    assert result.exit_code == 0
    assert '"ODK-TODO-001"' in result.output


# --- show ---


def test_show_existing(project: Path) -> None:
    from odk.core.todo_manager import TodoManager

    mgr = TodoManager(project)
    mgr.register(file="svc.py", line=10, method="Svc.create", description="Create service")

    with patch("odk.cli.todo_cmd.Path") as mock_path:
        mock_path.cwd.return_value = project
        result = runner.invoke(app, ["todo", "show", "ODK-TODO-001"])
    assert result.exit_code == 0
    assert "svc.py" in result.output
    assert "Svc.create" in result.output


def test_show_not_found(project: Path) -> None:
    with patch("odk.cli.todo_cmd.Path") as mock_path:
        mock_path.cwd.return_value = project
        result = runner.invoke(app, ["todo", "show", "ODK-TODO-999"])
    assert result.exit_code == 1


# --- assign ---


def test_assign_cli(project: Path) -> None:
    from odk.core.todo_manager import TodoManager

    mgr = TodoManager(project)
    mgr.register(file="a.py", line=1, method="A.x")

    with patch("odk.cli.todo_cmd.Path") as mock_path:
        mock_path.cwd.return_value = project
        result = runner.invoke(app, ["todo", "assign", "ODK-TODO-001", "T-042"])
    assert result.exit_code == 0
    assert "Assigned" in result.output

    item = mgr.get("ODK-TODO-001")
    assert item.task_id == "T-042"


# --- done ---


def test_done_cli_success(project: Path) -> None:
    from odk.core.todo_manager import TodoManager

    # Create a resolved file
    src = project / "a.py"
    src.write_text("def x():\n    return 1\n")

    mgr = TodoManager(project)
    mgr.register(file="a.py", line=1, method="A.x")

    with patch("odk.cli.todo_cmd.Path") as mock_path:
        mock_path.cwd.return_value = project
        result = runner.invoke(app, ["todo", "done", "ODK-TODO-001"])
    assert result.exit_code == 0
    assert "marked as done" in result.output


def test_done_cli_fails_if_not_resolved(project: Path) -> None:
    from odk.core.todo_manager import TodoManager

    src = project / "a.py"
    src.write_text("def x():\n    raise NotImplementedError  # ODK-TODO-001: todo\n")

    mgr = TodoManager(project)
    mgr.register(file="a.py", line=2, method="A.x")

    with patch("odk.cli.todo_cmd.Path") as mock_path:
        mock_path.cwd.return_value = project
        result = runner.invoke(app, ["todo", "done", "ODK-TODO-001"])
    assert result.exit_code == 1


# --- coverage ---


def test_coverage_empty(project: Path) -> None:
    with patch("odk.cli.todo_cmd.Path") as mock_path:
        mock_path.cwd.return_value = project
        result = runner.invoke(app, ["todo", "coverage"])
    assert result.exit_code == 0
    assert "No TODOs registered" in result.output


def test_coverage_with_items(project: Path) -> None:
    from odk.core.todo_manager import TodoManager

    mgr = TodoManager(project)
    mgr.register(file="a.py", line=1, method="A.x")
    mgr.register(file="b.py", line=1, method="B.y")

    with patch("odk.cli.todo_cmd.Path") as mock_path:
        mock_path.cwd.return_value = project
        result = runner.invoke(app, ["todo", "coverage"])
    assert result.exit_code == 0
    assert "Total:" in result.output
    assert "2" in result.output

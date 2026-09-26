"""Tests for ydk task commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from ydk.cli import app
from ydk.cli.task_cmd import _parse_depends_on_arg, _resolve_task_id
from ydk.models.pm import Dependency, DependencyType, TaskDetail, TaskSummary

runner = CliRunner()


def test_parse_depends_on_arg_comma_separated_single_flag() -> None:
    """A single --depends-on value with comma-joined deps splits into separate entries."""
    result = _parse_depends_on_arg(["103:blocks,104:blocks"])
    assert result == ["103", "104"]


def test_parse_depends_on_arg_comma_separated_mixed_types() -> None:
    """Comma-joined deps with mixed types parse independently."""
    result = _parse_depends_on_arg(["103:validates,104:blocks"])
    assert len(result) == 2
    assert result[0] == Dependency(task_id="103", type=DependencyType.VALIDATES)
    assert result[1] == "104"


def test_parse_depends_on_arg_repeated_flag_unchanged() -> None:
    """Repeated --depends-on flags still work as before."""
    result = _parse_depends_on_arg(["103:blocks", "104:blocks"])
    assert result == ["103", "104"]


def test_parse_depends_on_arg_no_comma_no_colon() -> None:
    """A single bare id with no comma or colon is returned unchanged."""
    result = _parse_depends_on_arg(["103"])
    assert result == ["103"]


def test_parse_depends_on_arg_invalid_type_raises() -> None:
    """An invalid dependency type still raises typer.BadParameter."""
    with pytest.raises(typer.BadParameter):
        _parse_depends_on_arg(["103:bogus"])


def test_resolve_task_id_reads_mapping_with_utf8_encoding(tmp_path: Path, monkeypatch) -> None:
    """_resolve_task_id reads .ydk/batch-mapping.json with explicit utf-8 encoding."""
    monkeypatch.chdir(tmp_path)
    ydk_dir = tmp_path / ".ydk"
    ydk_dir.mkdir()
    (ydk_dir / "batch-mapping.json").write_text('{"T-001": "42"}', encoding="utf-8")

    with patch("pathlib.Path.read_text", autospec=True, wraps=Path.read_text) as mock_read_text:
        resolved = _resolve_task_id("T-001")

    assert resolved == "42"
    assert mock_read_text.call_args.kwargs.get("encoding") == "utf-8"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("T-001", "42"), ("S-001", "17"), ("E-001", "9"), ("#12", "12"), ("12", "12"), ("T-5e9dbd18", "T-5e9dbd18")],
)
def test_resolve_task_id_resolves_all_mapped_placeholders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str, expected: str
) -> None:
    """_resolve_task_id resolves task/story/epic placeholders and normalizes '#N'."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ydk").mkdir()
    (tmp_path / ".ydk" / "batch-mapping.json").write_text(
        '{"T-001": "#42", "S-001": "#17", "E-001": "9"}', encoding="utf-8"
    )

    assert _resolve_task_id(raw) == expected


def test_task_create_resolves_mapped_depends_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--depends-on batch placeholders resolve via the mapping before use."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ydk").mkdir()
    (tmp_path / ".ydk" / "batch-mapping.json").write_text('{"T-001": "#42", "T-002": "#43"}', encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "task",
            "create",
            "--title",
            "x",
            "--story",
            "#1",
            "--acceptance",
            "a",
            "--test-strategy",
            "t",
            "--depends-on",
            "T-001,T-002:validates",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "'42'" in result.output
    assert "task_id='43'" in result.output
    assert "T-001" not in result.output


def test_task_validate_dag_valid(tmp_path: Path) -> None:
    """ydk task validate-dag exits 0 for a valid DAG."""
    mock_repo = MagicMock()
    t1 = TaskDetail(id="T-001", title="First", status="open", dependencies=[])
    t2 = TaskDetail(id="T-002", title="Second", status="open", dependencies=["T-001"])
    t3 = TaskDetail(id="T-003", title="Third", status="open", dependencies=["T-001"])
    mock_repo.list_tasks.return_value = [
        TaskSummary(id="T-001", title="First", status="open", dependencies_met=True),
        TaskSummary(id="T-002", title="Second", status="open", dependencies_met=True),
        TaskSummary(id="T-003", title="Third", status="open", dependencies_met=True),
    ]
    mock_repo.get_task.side_effect = lambda tid: {"T-001": t1, "T-002": t2, "T-003": t3}[tid]
    with patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo):
        result = runner.invoke(app, ["task", "validate-dag"])
    assert result.exit_code == 0
    assert "DAG is valid" in result.output


def test_task_validate_dag_cyclic() -> None:
    """ydk task validate-dag exits 1 for a cyclic DAG."""
    mock_repo = MagicMock()
    t1 = TaskDetail(id="T-001", title="First", status="open", dependencies=["T-002"])
    t2 = TaskDetail(id="T-002", title="Second", status="open", dependencies=["T-001"])
    mock_repo.list_tasks.return_value = [
        TaskSummary(id="T-001", title="First", status="open", dependencies_met=True),
        TaskSummary(id="T-002", title="Second", status="open", dependencies_met=True),
    ]
    mock_repo.get_task.side_effect = lambda tid: {"T-001": t1, "T-002": t2}[tid]
    with patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo):
        result = runner.invoke(app, ["task", "validate-dag"])
    assert result.exit_code != 0
    assert "FAILED" in result.output


def test_task_validate_dag_no_tasks() -> None:
    """ydk task validate-dag with no tasks shows message."""
    mock_repo = MagicMock()
    mock_repo.list_tasks.return_value = []
    with patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo):
        result = runner.invoke(app, ["task", "validate-dag"])
    assert result.exit_code == 0
    assert "No tasks found" in result.output

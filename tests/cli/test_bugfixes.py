"""Tests for E2E bug fixes — covers Fixes 1-9 from the E2E test report."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import yaml
from typer.testing import CliRunner

from ydk.cli import app
from ydk.core.config import DEFAULT_CONFIG
from ydk.models.pm import TaskSummary
from ydk.models.verification import CheckResult

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _setup_project(tmp_path: Path) -> None:
    """Write valid config and manifest."""
    config_dir = tmp_path / ".ydk"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(yaml.dump(DEFAULT_CONFIG, default_flow_style=False))
    (config_dir / "manifest.yaml").write_text(
        yaml.dump(
            {
                "last_task_id": 0,
                "last_story_id": 0,
                "last_epic_id": 0,
                "epics": {"E-001": {"title": "Auth", "status": "open", "stories": []}},
                "stories": {"S-001": {"title": "Login", "epic": "E-001", "status": "open", "tasks": []}},
                "tasks": {},
            },
            default_flow_style=False,
        )
    )


# ─── Fix 1: task create CLI command ──────────────────────────────────────


def test_task_create(tmp_path: Path, monkeypatch: object) -> None:
    """ydk task create creates a task and exits 0."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_project(tmp_path)
    result = runner.invoke(
        app,
        ["task", "create", "--title", "Build login form", "--story", "S-001"],
    )
    assert result.exit_code == 0
    assert "T-" in result.output
    assert "Build login form" in result.output


def test_task_create_with_options(tmp_path: Path, monkeypatch: object) -> None:
    """ydk task create with all options stores them correctly."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_project(tmp_path)
    result = runner.invoke(
        app,
        [
            "task",
            "create",
            "--title",
            "Build form",
            "--story",
            "S-001",
            "--description",
            "Build the login form",
            "--test-strategy",
            "Unit tests",
        ],
    )
    assert result.exit_code == 0
    task_files = list((tmp_path / ".ydk" / "tasks").glob("T-*.md"))
    assert len(task_files) == 1
    file_content = task_files[0].read_text()
    assert "Build the login form" in file_content


def test_task_create_json_format(tmp_path: Path, monkeypatch: object) -> None:
    """ydk --format json task create outputs valid JSON."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_project(tmp_path)
    result = runner.invoke(
        app,
        ["--format", "json", "task", "create", "--title", "Test", "--story", "S-001"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["title"] == "Test"
    assert data["id"].startswith("T-")


# ─── Fix 2: spec check actually runs (mocked) ────────────────────────────


@patch("ydk.cli.spec_cmd._strands_available", return_value=False)
@patch("ydk.cli.spec_cmd._run_reviewer_agents", return_value=([], {}))
def test_spec_check_without_strands(
    mock_reviewers: MagicMock, mock_strands: MagicMock, tmp_path: Path, monkeypatch: object
) -> None:
    """ydk spec verify without strands skips LLM checks and still produces a report."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_project(tmp_path)
    # Create a spec file
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "api.md").write_text("# API Spec\nSome content")
    result = runner.invoke(app, ["spec", "verify", "--all-files"])
    assert result.exit_code == 0
    assert "Verification Report" in result.output


@patch("ydk.cli.spec_cmd._strands_available", return_value=True)
@patch("ydk.cli.spec_cmd._run_reviewer_agents")
def test_spec_check_with_strands_runs_eval(
    mock_run: MagicMock, mock_strands: MagicMock, tmp_path: Path, monkeypatch: object
) -> None:
    """ydk spec verify calls reviewer agents when strands is available."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_project(tmp_path)
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "api.md").write_text("# API Spec")
    from ydk.core.reviewer import ReviewResult

    mock_run.return_value = (
        [
            ReviewResult(reviewer_id="N01", name="Problem Statement", score=9, passed=True, reasoning="Good"),
        ],
        {},
    )
    result = runner.invoke(app, ["spec", "verify", "--all-files"])
    assert result.exit_code == 0
    mock_run.assert_called_once()
    assert "PASS" in result.output


# ─── Fix 3: Duration bug in verify_cmd.py ────────────────────────────────


def test_verify_duration_is_reasonable(monkeypatch: object) -> None:
    """verify run --name X should report duration < 1000 seconds."""
    plugin = MagicMock()
    plugin.name = "test-check"
    plugin.trigger = "git:pre-commit"

    monkeypatch.setattr(
        "ydk.cli.verify_cmd.Verifier.discover_plugins",
        lambda self: [plugin],
    )
    monkeypatch.setattr(
        "ydk.cli.verify_cmd.Verifier.filter_by_name",
        lambda self, plugins, name: [p for p in plugins if p.name == name],
    )
    monkeypatch.setattr(
        "ydk.cli.verify_cmd.Verifier.run_layer",
        AsyncMock(return_value=[CheckResult(name="test-check", passed=True, output="ok", duration_seconds=0.1)]),
    )

    result = runner.invoke(app, ["verify", "run", "--name", "test-check"])
    assert result.exit_code == 0
    # Extract the total duration from output like "ALL PASSED (0.0s)"
    for line in result.output.splitlines():
        if "ALL PASSED" in line:
            # Parse duration from "ALL PASSED (X.Xs)"
            import re

            match = re.search(r"\((\d+\.?\d*)s\)", line)
            if match:
                duration = float(match.group(1))
                assert duration < 1000, f"Duration {duration}s is unreasonable (unix timestamp leak?)"
            break


# ─── Fix 4: Nonexistent task returns friendly error ──────────────────────


@patch("ydk.cli.task_cmd._build_lifecycle")
def test_start_nonexistent_task_friendly_error(mock_build: MagicMock, tmp_path: Path, monkeypatch: object) -> None:
    """ydk task start T-999 shows friendly error, not traceback."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    # Satisfy precondition: todos.yaml must exist
    (tmp_path / ".ydk").mkdir(parents=True)
    (tmp_path / ".ydk" / "todos.yaml").write_text("todos: []")
    lc = MagicMock()
    lc.start.side_effect = FileNotFoundError("[Errno 2] No such file or directory: '.ydk/tasks/T-999.md'")
    mock_build.return_value = lc
    result = runner.invoke(app, ["task", "start", "T-999"])
    assert result.exit_code == 1
    assert "Error:" in result.output
    # Should NOT contain a Python traceback
    assert "Traceback" not in result.output


@patch("ydk.cli.task_cmd._build_lifecycle")
def test_comment_nonexistent_task_friendly_error(mock_build: MagicMock) -> None:
    """ydk task comment T-999 shows friendly error."""
    lc = MagicMock()
    lc.progress.side_effect = FileNotFoundError("No such file")
    mock_build.return_value = lc
    result = runner.invoke(app, ["task", "comment", "T-999", "test"])
    assert result.exit_code == 1
    assert "Error:" in result.output


@patch("ydk.cli.task_cmd._build_lifecycle")
def test_block_nonexistent_task_friendly_error(mock_build: MagicMock) -> None:
    """ydk task block T-999 shows friendly error."""
    lc = MagicMock()
    lc.block.side_effect = FileNotFoundError("No such file")
    mock_build.return_value = lc
    result = runner.invoke(app, ["task", "block", "T-999", "--reason", "code", "--detail", "broken"])
    assert result.exit_code == 1
    assert "Error:" in result.output


@patch("ydk.cli.task_cmd._build_lifecycle")
def test_done_nonexistent_task_friendly_error(mock_build: MagicMock) -> None:
    """ydk task done T-999 shows friendly error."""
    lc = MagicMock()
    lc.done.side_effect = FileNotFoundError("No such file")
    mock_build.return_value = lc
    result = runner.invoke(app, ["task", "done", "T-999"])
    assert result.exit_code == 1
    assert "Error:" in result.output


@patch("ydk.cli.task_cmd._build_lifecycle")
def test_add_subtask_nonexistent_task_friendly_error(mock_build: MagicMock) -> None:
    """ydk task add-subtask T-999 shows friendly error."""
    lc = MagicMock()
    lc.discover.side_effect = FileNotFoundError("No such file")
    mock_build.return_value = lc
    result = runner.invoke(app, ["task", "add-subtask", "T-999", "--title", "New"])
    assert result.exit_code == 1
    assert "Error:" in result.output


# ─── Fix 5: config show doesn't contain Rich markup tags ─────────────────


def test_config_show_no_raw_markup(tmp_path: Path, monkeypatch: object) -> None:
    """ydk config show should not output raw Rich markup like [bold]."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_project(tmp_path)
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    # The output should not contain literal Rich tags
    assert "[bold]" not in result.output
    assert "[/bold]" not in result.output


def test_config_show_json_format(tmp_path: Path, monkeypatch: object) -> None:
    """ydk --format json config show outputs valid JSON."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_project(tmp_path)
    result = runner.invoke(app, ["--format", "json", "config", "show"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "project" in data
    assert data["project"]["name"] == "my-project"


# ─── Fix 6: --format json produces valid JSON ────────────────────────────


def test_task_list_json_format() -> None:
    """ydk --format json task list outputs valid JSON."""
    mock_repo = MagicMock()
    mock_repo.list_tasks.return_value = [
        TaskSummary(id="T-a1b2c3d4", title="First", status="open", dependencies_met=True),
    ]
    with patch("ydk.repositories.factory.get_task_repository", return_value=mock_repo):
        result = runner.invoke(app, ["--format", "json", "task", "list"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"].startswith("T-")
    assert data[0]["title"] == "First"


def test_task_coverage_no_specs(tmp_path: Path, monkeypatch: object) -> None:
    """ydk task coverage with no spec files shows message."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_project(tmp_path)
    result = runner.invoke(app, ["task", "coverage"])
    assert result.exit_code == 0
    assert "No spec files found" in result.output


def test_task_coverage_finds_gaps(tmp_path: Path, monkeypatch: object) -> None:
    """ydk task coverage identifies uncovered spec sections."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_project(tmp_path)
    # Create spec files
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "auth.md").write_text("# Auth spec")
    (spec_dir / "data.md").write_text("# Data spec")
    result = runner.invoke(app, ["task", "coverage"])
    assert result.exit_code == 0
    assert "Coverage:" in result.output
    # With no stories pointing to these specs, all should be uncovered
    assert "Uncovered" in result.output


def test_task_coverage_json_format(tmp_path: Path, monkeypatch: object) -> None:
    """ydk --format json task coverage outputs valid JSON."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_project(tmp_path)
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "auth.md").write_text("# Auth spec")
    result = runner.invoke(app, ["--format", "json", "task", "coverage"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "total_sections" in data
    assert "uncovered" in data


# ─── Fix 8: task unblock ──────────────────────────────────────────────────


def test_task_unblock(tmp_path: Path, monkeypatch: object) -> None:
    """ydk task unblock changes status from blocked to in-progress."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_project(tmp_path)

    # Create a task first
    from ydk.models.pm import TaskCreate
    from ydk.repositories.local.tasks import LocalTaskRepository

    repo = LocalTaskRepository(tmp_path / ".ydk")
    created = repo.create_task(TaskCreate(title="Test task", story_id="S-001"))
    task_id = created.id

    # Manually set status to blocked
    repo.update_status(task_id, "blocked-by-code")
    repo.add_label(task_id, "blocked-by-code")

    # Unblock it
    result = runner.invoke(app, ["task", "unblock", task_id])
    assert result.exit_code == 0
    assert "unblocked" in result.output

    # Verify status changed
    task = repo.get_task(task_id)
    assert task.status == "in-progress"


def test_task_unblock_nonexistent_friendly_error() -> None:
    """ydk task unblock T-999 gives friendly error."""
    # No project setup -- should fail with FileNotFoundError caught gracefully
    with patch("ydk.cli.task_cmd._get_repo") as mock_get_repo:
        mock_repo = MagicMock()
        mock_repo.update_status.side_effect = FileNotFoundError("No such file")
        mock_get_repo.return_value = mock_repo
        result = runner.invoke(app, ["task", "unblock", "T-999"])
        assert result.exit_code == 1
        assert "Error:" in result.output


# ─── Fix 9: aws.profile is read in spec check ────────────────────────────


@patch("ydk.cli.spec_cmd._strands_available", return_value=True)
@patch("ydk.cli.spec_cmd._run_reviewer_agents")
def test_spec_check_reads_aws_profile(
    mock_run: MagicMock, mock_strands: MagicMock, tmp_path: Path, monkeypatch: object
) -> None:
    """ydk spec verify passes config (with aws.profile) to reviewer agents."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]

    # Set up config with aws.profile
    config = {**DEFAULT_CONFIG, "aws": {"profile": "my-test-profile", "region": "us-east-1"}}
    config_dir = tmp_path / ".ydk"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(yaml.dump(config, default_flow_style=False))

    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "api.md").write_text("# Spec")

    mock_run.return_value = []
    result = runner.invoke(app, ["spec", "verify", "--all-files"])
    assert result.exit_code == 0

    # Verify the reviewer agents were called with the config
    mock_run.assert_called_once()
    call_kwargs = mock_run.call_args
    # The config object is passed as `config` kwarg
    from ydk.models.config import YdkConfig

    cfg = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
    assert isinstance(cfg, YdkConfig)
    assert cfg.aws.profile == "my-test-profile"

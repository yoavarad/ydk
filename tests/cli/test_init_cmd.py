"""Tests for odk init command."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from typer.testing import CliRunner

from odk.cli import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def test_init_creates_config(tmp_path: Path, monkeypatch: object) -> None:
    """odk init --name myproject creates .odk/config.yaml."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["init", "--name", "myproject"])
    assert result.exit_code == 0
    assert "myproject" in result.output
    assert (tmp_path / ".odk" / "config.yaml").is_file()


def test_init_fails_when_config_exists(tmp_path: Path, monkeypatch: object) -> None:
    """odk init when config already exists exits non-zero."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    (tmp_path / ".odk").mkdir()
    (tmp_path / ".odk" / "config.yaml").write_text("project:\n  name: existing\n")
    result = runner.invoke(app, ["init", "--name", "myproject"])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_init_force_overwrites(tmp_path: Path, monkeypatch: object) -> None:
    """odk init --name myproject --force overwrites existing config."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    (tmp_path / ".odk").mkdir()
    (tmp_path / ".odk" / "config.yaml").write_text("project:\n  name: old\n")
    result = runner.invoke(app, ["init", "--name", "myproject", "--force"])
    assert result.exit_code == 0
    assert "myproject" in result.output


def test_init_creates_spec_directory(tmp_path: Path, monkeypatch: object) -> None:
    """odk init creates the docs/specs/ directory."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    runner.invoke(app, ["init", "--name", "myproject"])
    assert (tmp_path / "docs" / "specs").is_dir()


def test_init_creates_adrs_directory(tmp_path: Path, monkeypatch: object) -> None:
    """odk init creates the docs/adrs/ directory."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    runner.invoke(app, ["init", "--name", "myproject"])
    assert (tmp_path / "docs" / "adrs").is_dir()


def test_init_creates_project_rules(tmp_path: Path, monkeypatch: object) -> None:
    """odk init creates docs/project-rules.md."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    runner.invoke(app, ["init", "--name", "myproject"])
    rules = tmp_path / "docs" / "project-rules.md"
    assert rules.is_file()
    assert "Project Rules" in rules.read_text()


def test_init_runs_doctor(tmp_path: Path, monkeypatch: object) -> None:
    """odk init runs doctor checks at the end."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["init", "--name", "myproject"])
    assert "Python" in result.output
    assert "checks passed" in result.output


def test_init_hooks_use_verify_run_subcommand(tmp_path: Path, monkeypatch: object) -> None:
    """odk init creates hooks that use 'odk verify run --trigger' (not 'odk verify --trigger')."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    runner.invoke(app, ["init", "--name", "myproject"])

    pre_commit = tmp_path / ".odk" / "hooks" / "pre-commit"
    assert pre_commit.is_file()
    content = pre_commit.read_text()
    assert "odk verify run --trigger pre-commit" in content
    assert "odk verify --trigger pre-commit\n" not in content  # must NOT have old syntax

    pre_push = tmp_path / ".odk" / "hooks" / "pre-push"
    assert pre_push.is_file()
    content = pre_push.read_text()
    assert "odk verify run --trigger pre-push" in content
    assert "odk verify --trigger pre-push\n" not in content


def test_init_with_remote_flag(tmp_path: Path, monkeypatch: object) -> None:
    """odk init --remote github sets remote in config."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["init", "--name", "myproject", "--remote", "github"])
    assert result.exit_code == 0
    cfg = yaml.safe_load((tmp_path / ".odk" / "config.yaml").read_text())
    assert cfg["project"]["remote"] == "github"


def test_init_with_stack_flag(tmp_path: Path, monkeypatch: object) -> None:
    """odk init --stack python-fastapi populates verifications and stack field."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["init", "--name", "myproject", "--stack", "python-fastapi"])
    assert result.exit_code == 0
    cfg = yaml.safe_load((tmp_path / ".odk" / "config.yaml").read_text())
    assert cfg["project"]["stack"] == "python-fastapi"
    assert "lint-ruff" in cfg["verification"]["enabled"]
    assert "tests-pytest" in cfg["verification"]["enabled"]
    assert "fastapi-route-delegation" in cfg["verification"]["enabled"]


def test_init_with_stack_and_remote(tmp_path: Path, monkeypatch: object) -> None:
    """odk init --stack python-fastapi --remote github sets both."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["init", "--name", "api", "--stack", "python-fastapi", "--remote", "github"])
    assert result.exit_code == 0
    cfg = yaml.safe_load((tmp_path / ".odk" / "config.yaml").read_text())
    assert cfg["project"]["remote"] == "github"
    assert cfg["project"]["stack"] == "python-fastapi"


def test_init_without_stack_has_no_enabled_list(tmp_path: Path, monkeypatch: object) -> None:
    """odk init without --stack does not populate verification.enabled."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["init", "--name", "plain"])
    assert result.exit_code == 0
    cfg = yaml.safe_load((tmp_path / ".odk" / "config.yaml").read_text())
    # No verification section or empty enabled list
    assert cfg.get("verification", {}).get("enabled", []) == []


def test_init_shows_summary_table(tmp_path: Path, monkeypatch: object) -> None:
    """odk init prints a Rich summary table with project name, remote, stack, hooks, and schemas."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["init", "--name", "myproject", "--remote", "github", "--stack", "python-fastapi"])
    assert result.exit_code == 0
    assert "Project Summary" in result.output
    assert "myproject" in result.output
    assert "github" in result.output
    assert "python-fastapi" in result.output


def test_init_copies_spec_reviewers(tmp_path: Path, monkeypatch: object) -> None:
    """odk init copies built-in spec-reviewer YAMLs to .odk/spec-reviewers/."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["init", "--name", "myproject"])
    assert result.exit_code == 0

    reviewers_dir = tmp_path / ".odk" / "spec-reviewers"
    assert reviewers_dir.is_dir()
    yaml_files = list(reviewers_dir.glob("*.yaml"))
    assert len(yaml_files) == 10
    # Verify custom/ subdirectory exists
    assert (reviewers_dir / "custom").is_dir()


def test_init_does_not_overwrite_existing_reviewers(tmp_path: Path, monkeypatch: object) -> None:
    """odk init --force preserves user-modified reviewer YAMLs."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    # First init
    runner.invoke(app, ["init", "--name", "myproject"])
    # Modify a reviewer YAML
    n01 = tmp_path / ".odk" / "spec-reviewers" / "n01.yaml"
    n01.write_text("id: N01\nname: Modified\ntools: []\nsystem_prompt: Custom.\n")
    # Force re-init
    runner.invoke(app, ["init", "--name", "myproject", "--force"])
    # Should NOT overwrite the modified file
    assert "Modified" in n01.read_text()


def test_init_installs_subagent_stop_hook(tmp_path: Path, monkeypatch: object) -> None:
    """odk init installs .claude/hooks/check-task-complete.sh and SubagentStop in settings."""
    import json

    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    runner.invoke(app, ["init", "--name", "myproject"])

    # Verify the hook script is installed and executable
    hook_script = tmp_path / ".claude" / "hooks" / "check-task-complete.sh"
    assert hook_script.is_file()
    assert hook_script.stat().st_mode & 0o100  # executable
    content = hook_script.read_text()
    assert "active-task.json" in content
    assert "exit 2" in content

    # Verify settings.json includes SubagentStop
    settings_path = tmp_path / ".claude" / "settings.json"
    assert settings_path.is_file()
    settings = json.loads(settings_path.read_text())
    assert "SubagentStop" in settings["hooks"]
    stop_hooks = settings["hooks"]["SubagentStop"]
    assert any("check-task-complete.sh" in h["hooks"][0]["command"] for h in stop_hooks)


def test_init_installs_guard_hook(tmp_path: Path, monkeypatch: object) -> None:
    """odk init installs .claude/hooks/guard.py with PreToolUse and permissions.allow."""
    import json

    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    runner.invoke(app, ["init", "--name", "myproject"])

    # Verify guard.py is installed and executable
    guard_script = tmp_path / ".claude" / "hooks" / "guard.py"
    assert guard_script.is_file()
    assert guard_script.stat().st_mode & 0o100  # executable
    content = guard_script.read_text()
    assert "select.select" in content
    assert "no-manual-pr" in content
    assert "no-proof-tamper" in content
    assert "no-noqa" in content
    assert "no-mock-internals" in content
    assert "stage-gate" in content
    assert "sys.exit(2)" in content

    # Verify settings.json includes PreToolUse with guard.py
    settings_path = tmp_path / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text())
    assert "PreToolUse" in settings["hooks"]
    pre_hooks = settings["hooks"]["PreToolUse"]
    assert len(pre_hooks) == 1
    assert pre_hooks[0]["matcher"] == "Edit|Write|Bash"
    assert "guard.py" in pre_hooks[0]["hooks"][0]["command"]

    # Verify permissions.allow is set for non-interactive mode
    assert "permissions" in settings
    assert "Bash(*)" in settings["permissions"]["allow"]
    assert "Read(*)" in settings["permissions"]["allow"]
    assert "Edit(*)" in settings["permissions"]["allow"]
    assert "Write(*)" in settings["permissions"]["allow"]

"""Tests for the guard system: check-guard CLI, run_guard, and ProjectState."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

if TYPE_CHECKING:
    import pytest

from ydk.cli.main import app
from ydk.core.state import ProjectState
from ydk.core.verifier import Verifier

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_GUARD = FIXTURES / "sample-guard"

runner = CliRunner()


def _install_guard(project_root: Path, fixture: Path = SAMPLE_GUARD) -> None:
    """Copy a guard fixture into the project's .ydk/verifications/ dir."""
    dest = project_root / ".ydk" / "verifications" / fixture.name
    shutil.copytree(fixture, dest)


class TestRunGuard:
    """Unit tests for Verifier.run_guard()."""

    def test_passes_when_no_guard_plugins(self, tmp_path: Path) -> None:
        """No guard plugins -> allow (True, empty message)."""
        v = Verifier(project_root=tmp_path, use_cache=False)
        passed, msg = v.run_guard("guard:edit", {"project_root": str(tmp_path)})
        assert passed is True
        assert msg == ""

    def test_blocks_when_guard_fails(self, tmp_path: Path) -> None:
        """Guard plugin returns passed=false -> block."""
        _install_guard(tmp_path)
        v = Verifier(project_root=tmp_path, use_cache=False)
        context = {
            "project_root": str(tmp_path),
            "trigger": "guard:edit",
            "file_path": "blocked/secret.py",
            "tool_name": "Edit",
        }
        passed, msg = v.run_guard("guard:edit", context)
        assert passed is False
        assert "blocked/" in msg.lower() or "BLOCKED" in msg

    def test_passes_when_all_guards_pass(self, tmp_path: Path) -> None:
        """All guard plugins pass -> allow."""
        _install_guard(tmp_path)
        v = Verifier(project_root=tmp_path, use_cache=False)
        context = {
            "project_root": str(tmp_path),
            "trigger": "guard:edit",
            "file_path": "src/app/main.py",
            "tool_name": "Edit",
        }
        passed, msg = v.run_guard("guard:edit", context)
        assert passed is True
        assert msg == ""

    def test_reads_context_from_plugin(self, tmp_path: Path) -> None:
        """Context JSON is piped correctly to plugin."""
        _install_guard(tmp_path)
        v = Verifier(project_root=tmp_path, use_cache=False)
        # The plugin checks file_path — prove it actually reads context
        context = {
            "project_root": str(tmp_path),
            "trigger": "guard:edit",
            "file_path": "blocked/foo.py",
            "new_content": "x = 1",
            "tool_name": "Edit",
        }
        passed, msg = v.run_guard("guard:edit", context)
        assert passed is False
        assert "foo.py" in msg

    def test_guard_command_trigger_not_matched_by_edit_guard(self, tmp_path: Path) -> None:
        """guard:command trigger does not match a guard:edit plugin."""
        _install_guard(tmp_path)
        v = Verifier(project_root=tmp_path, use_cache=False)
        context = {
            "project_root": str(tmp_path),
            "trigger": "guard:command",
            "command": "rm -rf /",
            "tool_name": "Bash",
        }
        # sample-guard is guard:edit, so guard:command should pass (no matching plugins)
        passed, msg = v.run_guard("guard:command", context)
        assert passed is True
        assert msg == ""


class TestCheckGuardCLI:
    """Integration tests for `ydk verify check-guard`."""

    def test_exits_0_when_no_guard_plugins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No guard plugins -> exit 0."""
        monkeypatch.chdir(tmp_path)
        context = json.dumps({"project_root": str(tmp_path), "trigger": "guard:edit", "file_path": "src/x.py"})
        result = runner.invoke(app, ["verify", "check-guard", "guard:edit"], input=context)
        assert result.exit_code == 0

    def test_exits_2_when_guard_blocks(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Guard blocks -> exit 2."""
        monkeypatch.chdir(tmp_path)
        _install_guard(tmp_path)
        context = json.dumps(
            {
                "project_root": str(tmp_path),
                "trigger": "guard:edit",
                "file_path": "blocked/secret.py",
                "tool_name": "Edit",
            }
        )
        result = runner.invoke(app, ["verify", "check-guard", "guard:edit"], input=context)
        assert result.exit_code == 2

    def test_exits_0_when_guard_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Guard passes -> exit 0."""
        monkeypatch.chdir(tmp_path)
        _install_guard(tmp_path)
        context = json.dumps(
            {
                "project_root": str(tmp_path),
                "trigger": "guard:edit",
                "file_path": "src/main.py",
                "tool_name": "Edit",
            }
        )
        result = runner.invoke(app, ["verify", "check-guard", "guard:edit"], input=context)
        assert result.exit_code == 0

    def test_rejects_non_guard_trigger(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-guard trigger -> exit 1."""
        monkeypatch.chdir(tmp_path)
        context = json.dumps({"project_root": str(tmp_path)})
        result = runner.invoke(app, ["verify", "check-guard", "git:pre-commit"], input=context)
        assert result.exit_code == 1

    def test_invalid_json_stdin_does_not_crash(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Invalid JSON on stdin -> doesn't crash (no traceback), guard still runs."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["verify", "check-guard", "guard:edit"], input="not json{{{")
        # Doesn't crash with traceback — returns cleanly (0 or 2 depending on guards)
        assert result.exit_code in (0, 2)
        assert "Traceback" not in (result.output or "")


class TestProjectState:
    """Tests for ProjectState read/write/update."""

    def test_read_default_when_no_file(self, tmp_path: Path) -> None:
        """No state file -> returns default state."""
        state = ProjectState(tmp_path)
        assert state.read() == {"stage": "00"}

    def test_write_and_read_roundtrip(self, tmp_path: Path) -> None:
        """Write state, then read it back."""
        state = ProjectState(tmp_path)
        state.write({"stage": "02", "tdd_phase": "red"})
        assert state.read() == {"stage": "02", "tdd_phase": "red"}

    def test_update_merges(self, tmp_path: Path) -> None:
        """Update merges new keys into existing state."""
        state = ProjectState(tmp_path)
        state.write({"stage": "01", "existing_key": "value"})
        result = state.update(stage="02", new_key="new_value")
        assert result == {"stage": "02", "existing_key": "value", "new_key": "new_value"}
        # Verify persisted
        assert state.read() == result

    def test_update_creates_file_if_missing(self, tmp_path: Path) -> None:
        """Update creates .ydk/state.json if it doesn't exist."""
        state = ProjectState(tmp_path)
        result = state.update(stage="01")
        assert result == {"stage": "01"}
        assert state.path.exists()

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Write creates .ydk/ directory if needed."""
        state = ProjectState(tmp_path)
        assert not state.path.parent.exists()
        state.write({"stage": "00"})
        assert state.path.exists()

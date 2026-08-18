"""Tests for TDD guard plugins: tdd-guard (edit) and tdd-guard-cmd (command).

Tests the full TDD state machine: red → green → refactor → red.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ydk.core.verifier import Verifier

VERIFICATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "verifications"
TDD_GUARD_DIR = VERIFICATIONS_DIR / "tdd-guard"
TDD_GUARD_CMD_DIR = VERIFICATIONS_DIR / "tdd-guard-cmd"

STATE_FILE = ".ydk/tdd-state.json"


def _activate_tdd_state(project_root: Path) -> None:
    """Create default .ydk/tdd-state.json to activate the TDD guard."""
    _write_state(
        project_root,
        {"phase": "red", "test_files_written": [], "test_run_after_write": False, "active_task": None},
    )


def _install_tdd_guard(project_root: Path) -> None:
    """Install tdd-guard plugin into project's .ydk/verifications/ and activate state."""
    dest = project_root / ".ydk" / "verifications" / "tdd-guard"
    shutil.copytree(TDD_GUARD_DIR, dest)
    _activate_tdd_state(project_root)


def _install_tdd_guard_cmd(project_root: Path) -> None:
    """Install tdd-guard-cmd plugin into project's .ydk/verifications/ and activate state."""
    dest = project_root / ".ydk" / "verifications" / "tdd-guard-cmd"
    shutil.copytree(TDD_GUARD_CMD_DIR, dest)
    _activate_tdd_state(project_root)


def _install_both(project_root: Path) -> None:
    """Install both tdd-guard plugins."""
    _install_tdd_guard(project_root)
    _install_tdd_guard_cmd(project_root)


def _read_state(project_root: Path) -> dict:
    """Read TDD state from project."""
    state_path = project_root / STATE_FILE
    if state_path.exists():
        return json.loads(state_path.read_text())
    return {"phase": "red", "test_files_written": [], "test_run_after_write": False, "active_task": None}


def _write_state(project_root: Path, state: dict) -> None:
    """Write TDD state to project."""
    state_path = project_root / STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))


class TestTddGuardEdit:
    """Tests for tdd-guard (guard:edit trigger)."""

    def test_blocks_source_write_when_no_test(self, tmp_path: Path) -> None:
        """In RED phase with no tests written, source edits blocked."""
        _install_tdd_guard(tmp_path)
        v = Verifier(project_root=tmp_path, use_cache=False)
        context = {
            "project_root": str(tmp_path),
            "trigger": "guard:edit",
            "file_path": "src/app/core/services/strategy_service.py",
            "tool_name": "Edit",
        }
        passed, msg = v.run_guard("guard:edit", context)
        assert passed is False
        assert "BLOCKED" in msg
        assert "RED" in msg or "red" in msg.lower()

    def test_allows_test_write_in_red_phase(self, tmp_path: Path) -> None:
        """Writing tests is always allowed."""
        _install_tdd_guard(tmp_path)
        v = Verifier(project_root=tmp_path, use_cache=False)
        context = {
            "project_root": str(tmp_path),
            "trigger": "guard:edit",
            "file_path": "tests/core/test_strategy_service.py",
            "tool_name": "Edit",
        }
        passed, _ = v.run_guard("guard:edit", context)
        assert passed is True

    def test_allows_source_write_after_test_written_and_run(self, tmp_path: Path) -> None:
        """In GREEN phase, source edits allowed."""
        _install_tdd_guard(tmp_path)
        # Set state to green
        _write_state(
            tmp_path,
            {
                "phase": "green",
                "test_files_written": ["tests/core/test_foo.py"],
                "test_run_after_write": True,
                "active_task": None,
            },
        )
        v = Verifier(project_root=tmp_path, use_cache=False)
        context = {
            "project_root": str(tmp_path),
            "trigger": "guard:edit",
            "file_path": "src/app/core/services/strategy_service.py",
            "tool_name": "Edit",
        }
        passed, _ = v.run_guard("guard:edit", context)
        assert passed is True

    def test_allows_non_source_files_always(self, tmp_path: Path) -> None:
        """docs/, .ydk/, scripts/ etc. always allowed regardless of phase."""
        _install_tdd_guard(tmp_path)
        v = Verifier(project_root=tmp_path, use_cache=False)

        non_source_files = [
            "docs/README.md",
            ".ydk/state.json",
            ".claude/settings.json",
            "scripts/deploy.sh",
        ]
        for file_path in non_source_files:
            context = {
                "project_root": str(tmp_path),
                "trigger": "guard:edit",
                "file_path": file_path,
                "tool_name": "Edit",
            }
            passed, msg = v.run_guard("guard:edit", context)
            assert passed is True, f"Expected {file_path} to be allowed, got: {msg}"

    def test_records_test_file_in_state(self, tmp_path: Path) -> None:
        """Writing a test file updates tdd-state.json."""
        _install_tdd_guard(tmp_path)
        v = Verifier(project_root=tmp_path, use_cache=False)
        context = {
            "project_root": str(tmp_path),
            "trigger": "guard:edit",
            "file_path": "tests/core/test_new_feature.py",
            "tool_name": "Edit",
        }
        passed, _ = v.run_guard("guard:edit", context)
        assert passed is True

        state = _read_state(tmp_path)
        assert "tests/core/test_new_feature.py" in state["test_files_written"]

    def test_blocks_source_when_test_written_but_not_run(self, tmp_path: Path) -> None:
        """In RED phase with tests written but not run, source edits still blocked."""
        _install_tdd_guard(tmp_path)
        _write_state(
            tmp_path,
            {
                "phase": "red",
                "test_files_written": ["tests/core/test_foo.py"],
                "test_run_after_write": False,
                "active_task": None,
            },
        )
        v = Verifier(project_root=tmp_path, use_cache=False)
        context = {
            "project_root": str(tmp_path),
            "trigger": "guard:edit",
            "file_path": "src/app/main.py",
            "tool_name": "Edit",
        }
        passed, msg = v.run_guard("guard:edit", context)
        assert passed is False
        assert "pytest" in msg.lower() or "run" in msg.lower()

    def test_allows_source_in_refactor_phase(self, tmp_path: Path) -> None:
        """In REFACTOR phase, source edits allowed."""
        _install_tdd_guard(tmp_path)
        _write_state(
            tmp_path,
            {
                "phase": "refactor",
                "test_files_written": ["tests/core/test_foo.py"],
                "test_run_after_write": True,
                "active_task": None,
            },
        )
        v = Verifier(project_root=tmp_path, use_cache=False)
        context = {
            "project_root": str(tmp_path),
            "trigger": "guard:edit",
            "file_path": "src/app/core/services/foo.py",
            "tool_name": "Edit",
        }
        passed, _ = v.run_guard("guard:edit", context)
        assert passed is True

    def test_transitions_red_to_green_when_test_written_and_run(self, tmp_path: Path) -> None:
        """Source edit in RED with tests + run triggers transition to green."""
        _install_tdd_guard(tmp_path)
        _write_state(
            tmp_path,
            {
                "phase": "red",
                "test_files_written": ["tests/core/test_foo.py"],
                "test_run_after_write": True,
                "active_task": None,
            },
        )
        v = Verifier(project_root=tmp_path, use_cache=False)
        context = {
            "project_root": str(tmp_path),
            "trigger": "guard:edit",
            "file_path": "src/app/core/services/foo.py",
            "tool_name": "Edit",
        }
        passed, _ = v.run_guard("guard:edit", context)
        assert passed is True  # Edit allowed because transition happened

        # Verify state was updated to green
        state = _read_state(tmp_path)
        assert state["phase"] == "green"

    def test_does_not_double_record_test_file(self, tmp_path: Path) -> None:
        """Writing the same test file twice doesn't duplicate in state."""
        _install_tdd_guard(tmp_path)
        v = Verifier(project_root=tmp_path, use_cache=False)
        context = {
            "project_root": str(tmp_path),
            "trigger": "guard:edit",
            "file_path": "tests/core/test_foo.py",
            "tool_name": "Edit",
        }
        v.run_guard("guard:edit", context)
        v.run_guard("guard:edit", context)

        state = _read_state(tmp_path)
        assert state["test_files_written"].count("tests/core/test_foo.py") == 1


class TestTddGuardCommand:
    """Tests for tdd-guard-cmd (guard:command trigger)."""

    def test_tracks_pytest_execution(self, tmp_path: Path) -> None:
        """Running pytest updates test_run_after_write."""
        _install_tdd_guard_cmd(tmp_path)
        _write_state(
            tmp_path,
            {
                "phase": "red",
                "test_files_written": ["tests/test_foo.py"],
                "test_run_after_write": False,
                "active_task": None,
            },
        )
        v = Verifier(project_root=tmp_path, use_cache=False)
        context = {
            "project_root": str(tmp_path),
            "trigger": "guard:command",
            "command": "pytest tests/ -q",
            "tool_name": "Bash",
        }
        passed, _ = v.run_guard("guard:command", context)
        assert passed is True

        state = _read_state(tmp_path)
        assert state["test_run_after_write"] is True
        assert state["phase"] == "green"

    def test_resets_on_git_commit(self, tmp_path: Path) -> None:
        """git commit resets to RED phase."""
        _install_tdd_guard_cmd(tmp_path)
        _write_state(
            tmp_path,
            {
                "phase": "refactor",
                "test_files_written": ["tests/test_foo.py"],
                "test_run_after_write": True,
                "active_task": "T-001",
            },
        )
        v = Verifier(project_root=tmp_path, use_cache=False)
        context = {
            "project_root": str(tmp_path),
            "trigger": "guard:command",
            "command": "git commit -m 'feat: add new feature'",
            "tool_name": "Bash",
        }
        passed, _ = v.run_guard("guard:command", context)
        assert passed is True

        state = _read_state(tmp_path)
        assert state["phase"] == "red"
        assert state["test_files_written"] == []
        assert state["test_run_after_write"] is False
        # active_task preserved
        assert state["active_task"] == "T-001"

    def test_ignores_non_pytest_commands(self, tmp_path: Path) -> None:
        """Other commands don't affect TDD state."""
        _install_tdd_guard_cmd(tmp_path)
        _write_state(
            tmp_path,
            {
                "phase": "green",
                "test_files_written": ["tests/test_foo.py"],
                "test_run_after_write": True,
                "active_task": None,
            },
        )
        v = Verifier(project_root=tmp_path, use_cache=False)
        context = {
            "project_root": str(tmp_path),
            "trigger": "guard:command",
            "command": "ls -la src/",
            "tool_name": "Bash",
        }
        passed, _ = v.run_guard("guard:command", context)
        assert passed is True

        # State unchanged
        state = _read_state(tmp_path)
        assert state["phase"] == "green"

    def test_uv_run_pytest_also_tracked(self, tmp_path: Path) -> None:
        """uv run pytest is also detected as a pytest command."""
        _install_tdd_guard_cmd(tmp_path)
        _write_state(
            tmp_path,
            {
                "phase": "red",
                "test_files_written": ["tests/test_foo.py"],
                "test_run_after_write": False,
                "active_task": None,
            },
        )
        v = Verifier(project_root=tmp_path, use_cache=False)
        context = {
            "project_root": str(tmp_path),
            "trigger": "guard:command",
            "command": "uv run pytest tests/ -q --tb=short",
            "tool_name": "Bash",
        }
        passed, _ = v.run_guard("guard:command", context)
        assert passed is True

        state = _read_state(tmp_path)
        assert state["test_run_after_write"] is True
        assert state["phase"] == "green"

    def test_pytest_in_green_transitions_to_refactor(self, tmp_path: Path) -> None:
        """Running pytest in green phase transitions to refactor."""
        _install_tdd_guard_cmd(tmp_path)
        _write_state(
            tmp_path,
            {
                "phase": "green",
                "test_files_written": ["tests/test_foo.py"],
                "test_run_after_write": True,
                "active_task": None,
            },
        )
        v = Verifier(project_root=tmp_path, use_cache=False)
        context = {
            "project_root": str(tmp_path),
            "trigger": "guard:command",
            "command": "pytest tests/ -q",
            "tool_name": "Bash",
        }
        passed, _ = v.run_guard("guard:command", context)
        assert passed is True

        state = _read_state(tmp_path)
        assert state["phase"] == "refactor"


class TestTddStateMachine:
    """Integration tests for the full TDD state machine cycle."""

    def test_full_cycle_red_green_refactor(self, tmp_path: Path) -> None:
        """Complete TDD cycle: write test → run (fail) → implement → run (pass) → commit → red."""
        _install_both(tmp_path)
        v = Verifier(project_root=tmp_path, use_cache=False)

        # Step 1: In RED — source edit blocked
        context_src = {
            "project_root": str(tmp_path),
            "trigger": "guard:edit",
            "file_path": "src/core/service.py",
            "tool_name": "Edit",
        }
        passed, _ = v.run_guard("guard:edit", context_src)
        assert passed is False, "Source edit should be blocked in RED"

        # Step 2: Write a test — allowed
        context_test = {
            "project_root": str(tmp_path),
            "trigger": "guard:edit",
            "file_path": "tests/core/test_service.py",
            "tool_name": "Edit",
        }
        passed, _ = v.run_guard("guard:edit", context_test)
        assert passed is True, "Test write should be allowed in RED"

        # Step 3: Run pytest — transitions to green
        context_pytest = {
            "project_root": str(tmp_path),
            "trigger": "guard:command",
            "command": "pytest tests/core/test_service.py -q",
            "tool_name": "Bash",
        }
        passed, _ = v.run_guard("guard:command", context_pytest)
        assert passed is True

        state = _read_state(tmp_path)
        assert state["phase"] == "green"

        # Step 4: Source edit now allowed (GREEN)
        passed, _ = v.run_guard("guard:edit", context_src)
        assert passed is True, "Source edit should be allowed in GREEN"

        # Step 5: Run pytest again — transitions to refactor
        passed, _ = v.run_guard("guard:command", context_pytest)
        assert passed is True

        state = _read_state(tmp_path)
        assert state["phase"] == "refactor"

        # Step 6: Source edit still allowed (REFACTOR)
        passed, _ = v.run_guard("guard:edit", context_src)
        assert passed is True, "Source edit should be allowed in REFACTOR"

        # Step 7: Commit — resets to RED
        context_commit = {
            "project_root": str(tmp_path),
            "trigger": "guard:command",
            "command": "git commit -m 'feat: implement service'",
            "tool_name": "Bash",
        }
        passed, _ = v.run_guard("guard:command", context_commit)
        assert passed is True

        state = _read_state(tmp_path)
        assert state["phase"] == "red"
        assert state["test_files_written"] == []

        # Step 8: Source edit blocked again (back to RED)
        passed, _ = v.run_guard("guard:edit", context_src)
        assert passed is False, "Source edit should be blocked again in RED"

    def test_multiple_test_files_before_run(self, tmp_path: Path) -> None:
        """Multiple test files can be written before running pytest."""
        _install_both(tmp_path)
        v = Verifier(project_root=tmp_path, use_cache=False)

        # Write multiple test files
        for test_file in ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]:
            context = {
                "project_root": str(tmp_path),
                "trigger": "guard:edit",
                "file_path": test_file,
                "tool_name": "Edit",
            }
            passed, _ = v.run_guard("guard:edit", context)
            assert passed is True

        state = _read_state(tmp_path)
        assert len(state["test_files_written"]) == 3

        # Source still blocked until pytest runs
        context_src = {
            "project_root": str(tmp_path),
            "trigger": "guard:edit",
            "file_path": "src/main.py",
            "tool_name": "Edit",
        }
        passed, _ = v.run_guard("guard:edit", context_src)
        assert passed is False

    def test_app_directory_also_guarded(self, tmp_path: Path) -> None:
        """Files under app/ are also guarded as source."""
        _install_tdd_guard(tmp_path)
        v = Verifier(project_root=tmp_path, use_cache=False)
        context = {
            "project_root": str(tmp_path),
            "trigger": "guard:edit",
            "file_path": "app/models/user.py",
            "tool_name": "Edit",
        }
        passed, msg = v.run_guard("guard:edit", context)
        assert passed is False
        assert "BLOCKED" in msg

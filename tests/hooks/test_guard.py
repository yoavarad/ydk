"""Tests for the unified PreToolUse guard script (.claude/hooks/guard.py).

Tests the guard logic by running it as a subprocess with JSON piped to stdin,
matching how Claude Code actually invokes PreToolUse hooks.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from ydk.cli.init_cmd import _GUARD_SCRIPT

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def guard_script(tmp_path: Path) -> Path:
    """Write guard.py to tmp_path and return its path."""
    script = tmp_path / "guard.py"
    script.write_text(_GUARD_SCRIPT, encoding="utf-8")
    script.chmod(0o755)
    return script


def _run_guard(guard_script: Path, data: dict, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run the guard script with JSON data piped to stdin."""
    return subprocess.run(
        [sys.executable, str(guard_script)],
        input=json.dumps(data),
        capture_output=True,
        text=True,
        cwd=cwd or guard_script.parent,
    )


class TestNoManualPr:
    """GUARD: no-manual-pr blocks gh pr create/merge."""

    def test_blocks_gh_pr_create(self, guard_script: Path) -> None:
        result = _run_guard(
            guard_script,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "gh pr create --title 'test' --body 'test'"},
                "cwd": str(guard_script.parent),
            },
        )
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr

    def test_blocks_gh_pr_merge(self, guard_script: Path) -> None:
        result = _run_guard(
            guard_script,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "gh pr merge 42 --squash"},
                "cwd": str(guard_script.parent),
            },
        )
        assert result.returncode == 2
        assert "ydk task done" in result.stderr

    def test_allows_gh_pr_view(self, guard_script: Path) -> None:
        result = _run_guard(
            guard_script,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "gh pr view 42"},
                "cwd": str(guard_script.parent),
            },
        )
        assert result.returncode == 0


class TestNoProofTamper:
    """GUARD: no-proof-tamper blocks edits to .ydk/proofs/ (except summary.md)."""

    def test_blocks_proof_edit(self, guard_script: Path) -> None:
        result = _run_guard(
            guard_script,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": ".ydk/proofs/T-001/pytest.txt", "new_string": "fake"},
                "cwd": str(guard_script.parent),
            },
        )
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr

    def test_allows_summary_md(self, guard_script: Path) -> None:
        result = _run_guard(
            guard_script,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": ".ydk/proofs/T-001/summary.md", "new_string": "notes"},
                "cwd": str(guard_script.parent),
            },
        )
        assert result.returncode == 0

    def test_allows_non_proof_file(self, guard_script: Path) -> None:
        result = _run_guard(
            guard_script,
            {
                "tool_name": "Write",
                "tool_input": {"file_path": "src/main.py", "content": "print('hello')"},
                "cwd": str(guard_script.parent),
            },
        )
        assert result.returncode == 0


class TestNoNoqa:
    """GUARD: no-noqa blocks suppression markers in non-test files."""

    def test_blocks_noqa_in_source(self, guard_script: Path) -> None:
        result = _run_guard(
            guard_script,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/app/main.py", "new_string": "x = 1  # noqa: E501"},
                "cwd": str(guard_script.parent),
            },
        )
        assert result.returncode == 2
        assert "noqa" in result.stderr

    def test_blocks_type_ignore_in_source(self, guard_script: Path) -> None:
        result = _run_guard(
            guard_script,
            {
                "tool_name": "Write",
                "tool_input": {"file_path": "src/util.py", "content": "x: int = 'bad'  # type: ignore"},
                "cwd": str(guard_script.parent),
            },
        )
        assert result.returncode == 2
        assert "type: ignore" in result.stderr

    def test_allows_noqa_in_tests(self, guard_script: Path) -> None:
        result = _run_guard(
            guard_script,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "tests/test_main.py", "new_string": "x = 1  # noqa: E501"},
                "cwd": str(guard_script.parent),
            },
        )
        assert result.returncode == 0

    def test_allows_clean_source_edit(self, guard_script: Path) -> None:
        result = _run_guard(
            guard_script,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/app/main.py", "new_string": "x = 1"},
                "cwd": str(guard_script.parent),
            },
        )
        assert result.returncode == 0


class TestNoMockInternals:
    """GUARD: no-mock-internals blocks @patch of app/src modules in tests."""

    def test_blocks_patch_app(self, guard_script: Path) -> None:
        result = _run_guard(
            guard_script,
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": "tests/test_service.py",
                    "new_string": '@patch("app.core.services.UserService")',
                },
                "cwd": str(guard_script.parent),
            },
        )
        assert result.returncode == 2
        assert "mock" in result.stderr.lower()

    def test_blocks_patch_src(self, guard_script: Path) -> None:
        result = _run_guard(
            guard_script,
            {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "tests/test_repo.py",
                    "content": '@patch("src.infra.repo.UserRepo")\ndef test_it(): pass',
                },
                "cwd": str(guard_script.parent),
            },
        )
        assert result.returncode == 2

    def test_allows_external_patch(self, guard_script: Path) -> None:
        result = _run_guard(
            guard_script,
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": "tests/test_service.py",
                    "new_string": '@patch("httpx.Client.get")',
                },
                "cwd": str(guard_script.parent),
            },
        )
        assert result.returncode == 0


class TestStageGate:
    """GUARD: stage-gate blocks source edits in early stages."""

    def test_blocks_source_in_stage_01(self, guard_script: Path, tmp_path: Path) -> None:
        # Create state file
        ydk_dir = tmp_path / ".ydk"
        ydk_dir.mkdir()
        (ydk_dir / "state.json").write_text(json.dumps({"stage": "01"}))

        result = _run_guard(
            guard_script,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/main.py", "new_string": "code"},
                "cwd": str(tmp_path),
            },
            cwd=tmp_path,
        )
        assert result.returncode == 2
        assert "Stage 01" in result.stderr

    def test_blocks_tests_in_stage_02(self, guard_script: Path, tmp_path: Path) -> None:
        ydk_dir = tmp_path / ".ydk"
        ydk_dir.mkdir()
        (ydk_dir / "state.json").write_text(json.dumps({"stage": "02"}))

        result = _run_guard(
            guard_script,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "tests/test_main.py", "new_string": "code"},
                "cwd": str(tmp_path),
            },
            cwd=tmp_path,
        )
        assert result.returncode == 2
        assert "Stage 02" in result.stderr

    def test_allows_source_in_stage_03(self, guard_script: Path, tmp_path: Path) -> None:
        ydk_dir = tmp_path / ".ydk"
        ydk_dir.mkdir()
        (ydk_dir / "state.json").write_text(json.dumps({"stage": "03"}))

        result = _run_guard(
            guard_script,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/main.py", "new_string": "code"},
                "cwd": str(tmp_path),
            },
            cwd=tmp_path,
        )
        assert result.returncode == 0

    def test_allows_ydk_files_in_early_stages(self, guard_script: Path, tmp_path: Path) -> None:
        ydk_dir = tmp_path / ".ydk"
        ydk_dir.mkdir()
        (ydk_dir / "state.json").write_text(json.dumps({"stage": "01"}))

        result = _run_guard(
            guard_script,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": ".ydk/config.yaml", "new_string": "name: test"},
                "cwd": str(tmp_path),
            },
            cwd=tmp_path,
        )
        assert result.returncode == 0


class TestEdgeCases:
    """Edge cases: no stdin, bad JSON, no data."""

    def test_no_stdin_allows(self, guard_script: Path) -> None:
        """No stdin data should allow (exit 0)."""
        result = subprocess.run(
            [sys.executable, str(guard_script)],
            input="",
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_bad_json_allows(self, guard_script: Path) -> None:
        """Invalid JSON should fail open (exit 0)."""
        result = subprocess.run(
            [sys.executable, str(guard_script)],
            input="not json at all",
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_absolute_file_path_normalized(self, guard_script: Path, tmp_path: Path) -> None:
        """Absolute file_path matching cwd is normalized correctly."""
        ydk_dir = tmp_path / ".ydk"
        ydk_dir.mkdir()
        (ydk_dir / "state.json").write_text(json.dumps({"stage": "01"}))

        result = _run_guard(
            guard_script,
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": f"{tmp_path}/src/main.py", "new_string": "code"},
                "cwd": str(tmp_path),
            },
            cwd=tmp_path,
        )
        assert result.returncode == 2  # Should still be blocked

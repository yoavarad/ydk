"""Tests for `ydk hooks` — commands invoked by git hooks."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

from typer.testing import CliRunner

from ydk.cli import app
from ydk.models.verification import CheckResult, VerificationReport

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _ok_report() -> VerificationReport:
    return VerificationReport(
        timestamp="2026-04-26T00:00:00Z",
        checks=[CheckResult(name="lint", passed=True, output="ok", duration_seconds=0.1)],
        all_passed=True,
        total_duration_seconds=0.1,
    )


def _fail_report() -> VerificationReport:
    return VerificationReport(
        timestamp="2026-04-26T00:00:00Z",
        checks=[CheckResult(name="lint", passed=False, output="bad", duration_seconds=0.1)],
        all_passed=False,
        total_duration_seconds=0.1,
    )


class TestHooksCommitMsg:
    def test_valid_message_exits_zero(self, tmp_path: Path) -> None:
        msg_file = tmp_path / "COMMIT_EDITMSG"
        msg_file.write_text("feat: add thing\n")
        result = runner.invoke(app, ["hooks", "commit-msg", str(msg_file)])
        assert result.exit_code == 0

    def test_invalid_message_exits_one_with_same_error_text(self, tmp_path: Path) -> None:
        msg_file = tmp_path / "COMMIT_EDITMSG"
        msg_file.write_text("not conventional\n")
        result = runner.invoke(app, ["hooks", "commit-msg", str(msg_file)])
        assert result.exit_code == 1
        combined = (result.output or "") + str(result.exception or "") + (result.stdout or "")
        assert "does not follow conventional commit format" in combined


class TestHooksPrePush:
    def test_runs_verification_and_propagates_pass(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.run_all",
            AsyncMock(return_value=_ok_report()),
        )
        result = runner.invoke(app, ["hooks", "pre-push"])
        assert result.exit_code == 0

    def test_runs_verification_and_propagates_failure(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.run_all",
            AsyncMock(return_value=_fail_report()),
        )
        result = runner.invoke(app, ["hooks", "pre-push"])
        assert result.exit_code == 1

    def test_skips_verification_when_verified_flag_fresh(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        flag = tmp_path / ".ydk" / ".verified"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(str(time.time()))
        # If verification ran, it would fail — proves the skip path was taken.
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.run_all",
            AsyncMock(return_value=_fail_report()),
        )
        result = runner.invoke(app, ["hooks", "pre-push"])
        assert result.exit_code == 0
        assert "skipping verification" in result.output
        assert not flag.exists()

    def test_runs_verification_when_verified_flag_stale(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        flag = tmp_path / ".ydk" / ".verified"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(str(time.time() - 301))
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.run_all",
            AsyncMock(return_value=_ok_report()),
        )
        result = runner.invoke(app, ["hooks", "pre-push"])
        assert result.exit_code == 0
        assert "skipping verification" not in result.output
        assert not flag.exists()

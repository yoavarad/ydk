"""Tests for odk.core.auto_repair -- RepairLoop and structured error output."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from odk.core.auto_repair import RepairLoop, RepairResult
from odk.models.verification import CheckResult, VerificationReport


def _ok_report() -> VerificationReport:
    return VerificationReport(
        timestamp="2026-04-28T00:00:00Z",
        checks=[
            CheckResult(name="lint", passed=True, output="All clean", duration_seconds=0.1),
            CheckResult(name="tests", passed=True, output="5 passed", duration_seconds=1.0),
        ],
        all_passed=True,
        total_duration_seconds=1.1,
    )


def _fail_report(
    *,
    output: str = "src/foo.py:10:5: E303 too many blank lines\nsrc/bar.py:22:1: F401 unused import",
) -> VerificationReport:
    return VerificationReport(
        timestamp="2026-04-28T00:00:00Z",
        checks=[
            CheckResult(name="lint", passed=False, output=output, duration_seconds=0.2),
            CheckResult(name="tests", passed=True, output="5 passed", duration_seconds=1.0),
        ],
        all_passed=False,
        total_duration_seconds=1.2,
    )


class TestFormatErrors:
    """Test error formatting from VerificationReport."""

    def test_format_errors_returns_valid_json(self) -> None:
        loop = RepairLoop()
        report = _fail_report()
        result = loop.format_errors(report)
        parsed = json.loads(result)
        assert "failed_checks" in parsed
        assert isinstance(parsed["failed_checks"], list)

    def test_format_errors_includes_check_name_and_output(self) -> None:
        loop = RepairLoop()
        report = _fail_report()
        parsed = json.loads(loop.format_errors(report))
        assert len(parsed["failed_checks"]) == 1
        check = parsed["failed_checks"][0]
        assert check["name"] == "lint"
        assert "output" in check

    def test_format_errors_skips_passing_checks(self) -> None:
        loop = RepairLoop()
        report = _ok_report()
        parsed = json.loads(loop.format_errors(report))
        assert parsed["failed_checks"] == []

    def test_format_errors_includes_all_passed_flag(self) -> None:
        loop = RepairLoop()
        report = _fail_report()
        parsed = json.loads(loop.format_errors(report))
        assert parsed["all_passed"] is False

    def test_format_errors_with_multiple_failures(self) -> None:
        report = VerificationReport(
            timestamp="2026-04-28T00:00:00Z",
            checks=[
                CheckResult(name="lint", passed=False, output="lint error", duration_seconds=0.1),
                CheckResult(name="types", passed=False, output="type error", duration_seconds=0.2),
            ],
            all_passed=False,
            total_duration_seconds=0.3,
        )
        loop = RepairLoop()
        parsed = json.loads(loop.format_errors(report))
        assert len(parsed["failed_checks"]) == 2


class TestRepairLoopRun:
    """Test retry loop with mock verifier."""

    @pytest.mark.asyncio
    async def test_passes_on_first_try(self) -> None:
        verifier = MagicMock()
        verifier.run_all = AsyncMock(return_value=_ok_report())
        loop = RepairLoop()
        result = await loop.run(verifier, max_retries=3)
        assert result.final_passed is True
        assert result.attempts == 1
        assert verifier.run_all.await_count == 1

    @pytest.mark.asyncio
    async def test_fails_then_passes(self) -> None:
        verifier = MagicMock()
        verifier.run_all = AsyncMock(side_effect=[_fail_report(), _ok_report()])
        loop = RepairLoop()
        result = await loop.run(verifier, max_retries=3)
        assert result.final_passed is True
        assert result.attempts == 2
        assert verifier.run_all.await_count == 2

    @pytest.mark.asyncio
    async def test_max_retries_reached(self) -> None:
        verifier = MagicMock()
        verifier.run_all = AsyncMock(return_value=_fail_report())
        loop = RepairLoop()
        result = await loop.run(verifier, max_retries=2)
        assert result.final_passed is False
        assert result.attempts == 2
        assert len(result.errors_per_attempt) == 2
        assert verifier.run_all.await_count == 2

    @pytest.mark.asyncio
    async def test_errors_per_attempt_tracks_each_run(self) -> None:
        fail1 = _fail_report(output="error A")
        fail2 = _fail_report(output="error B")
        ok = _ok_report()
        verifier = MagicMock()
        verifier.run_all = AsyncMock(side_effect=[fail1, fail2, ok])
        loop = RepairLoop()
        result = await loop.run(verifier, max_retries=5)
        assert result.final_passed is True
        assert result.attempts == 3
        assert len(result.errors_per_attempt) == 2

    @pytest.mark.asyncio
    async def test_default_max_retries_is_three(self) -> None:
        verifier = MagicMock()
        verifier.run_all = AsyncMock(return_value=_fail_report())
        loop = RepairLoop()
        result = await loop.run(verifier)
        assert result.attempts == 3
        assert result.final_passed is False


class TestRepairResult:
    """Test RepairResult model."""

    def test_repair_result_fields(self) -> None:
        result = RepairResult(
            attempts=2,
            final_passed=True,
            errors_per_attempt=["err1", "err2"],
        )
        assert result.attempts == 2
        assert result.final_passed is True
        assert len(result.errors_per_attempt) == 2

"""Tests for GateChecker."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from ydk.core.gate_checker import GateChecker
from ydk.models.gate import Gate, GateStatus, GateType


@pytest.fixture
def checker() -> GateChecker:
    return GateChecker()


class TestCheckPrMerged:
    def test_returns_true_when_merged(self, checker) -> None:
        with patch("ydk.core.gate_checker.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="MERGED\n", stderr="")
            assert checker.check_pr_merged("https://github.com/org/repo/pull/42") is True

    def test_returns_false_when_open(self, checker) -> None:
        with patch("ydk.core.gate_checker.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="OPEN\n", stderr="")
            assert checker.check_pr_merged("https://github.com/org/repo/pull/42") is False

    def test_returns_false_on_error(self, checker) -> None:
        with patch("ydk.core.gate_checker.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
            assert checker.check_pr_merged("https://github.com/org/repo/pull/42") is False


class TestCheckCiPassed:
    def test_returns_true_when_completed_success(self, checker) -> None:
        with patch("ydk.core.gate_checker.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="completed\tsuccess\n", stderr=""
            )
            assert checker.check_ci_passed("https://github.com/org/repo/actions/runs/123") is True

    def test_returns_false_when_in_progress(self, checker) -> None:
        with patch("ydk.core.gate_checker.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="in_progress\t\n", stderr=""
            )
            assert checker.check_ci_passed("https://github.com/org/repo/actions/runs/123") is False

    def test_returns_false_when_failed(self, checker) -> None:
        with patch("ydk.core.gate_checker.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="completed\tfailure\n", stderr=""
            )
            assert checker.check_ci_passed("https://github.com/org/repo/actions/runs/123") is False


class TestCheckTimer:
    def test_returns_true_when_duration_elapsed(self, checker) -> None:
        past = (datetime.now(UTC) - timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert checker.check_timer(past, duration_minutes=30) is True

    def test_returns_false_when_duration_not_elapsed(self, checker) -> None:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert checker.check_timer(now, duration_minutes=30) is False

    def test_returns_false_on_invalid_timestamp(self, checker) -> None:
        assert checker.check_timer("not-a-date", duration_minutes=30) is False


class TestCheckHuman:
    def test_returns_false_for_pending_gate(self, checker) -> None:
        assert checker.check_human("G-001") is False


class TestResolveGate:
    def test_resolves_gate_sets_status_and_timestamp(self, checker) -> None:
        gate = Gate(id="G-001", type=GateType.HUMAN, description="Approval")
        resolved = checker.resolve_gate(gate)
        assert resolved.status == GateStatus.RESOLVED
        assert resolved.resolved_at is not None

    def test_resolve_preserves_other_fields(self, checker) -> None:
        gate = Gate(
            id="G-002",
            type=GateType.PR_MERGED,
            description="Wait for PR",
            config={"pr_url": "https://example.com/pull/1"},
        )
        resolved = checker.resolve_gate(gate)
        assert resolved.id == "G-002"
        assert resolved.config == {"pr_url": "https://example.com/pull/1"}


class TestCheckGate:
    def test_pr_merged_gate_resolved(self, checker) -> None:
        gate = Gate(
            id="G-001",
            type=GateType.PR_MERGED,
            description="Wait for PR",
            config={"pr_url": "https://github.com/org/repo/pull/42"},
        )
        with patch("ydk.core.gate_checker.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="MERGED\n", stderr="")
            status = checker.check_gate(gate)
            assert status == GateStatus.RESOLVED

    def test_already_resolved_stays_resolved(self, checker) -> None:
        gate = Gate(
            id="G-005",
            type=GateType.HUMAN,
            description="Already approved",
            status=GateStatus.RESOLVED,
            resolved_at="2025-06-01T12:00:00Z",
        )
        status = checker.check_gate(gate)
        assert status == GateStatus.RESOLVED

    def test_timer_gate_resolved(self, checker) -> None:
        past = (datetime.now(UTC) - timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        gate = Gate(
            id="G-003",
            type=GateType.TIMER,
            description="Wait 30m",
            config={"created_at": past, "duration_minutes": "30"},
        )
        status = checker.check_gate(gate)
        assert status == GateStatus.RESOLVED

    def test_human_gate_always_pending(self, checker) -> None:
        gate = Gate(id="G-004", type=GateType.HUMAN, description="Approval needed")
        status = checker.check_gate(gate)
        assert status == GateStatus.PENDING

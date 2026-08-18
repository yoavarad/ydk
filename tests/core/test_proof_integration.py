"""Integration tests — verify save_report and task done with proof capture."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ydk.core.pr_template import PRBodyBuilder
from ydk.core.proof_capture import ProofCapture
from ydk.models.verification import CheckResult, VerificationReport

if TYPE_CHECKING:
    from pathlib import Path


def _make_report(task_id: str = "T-001") -> VerificationReport:
    checks = [
        CheckResult(name="ruff/check", passed=True, output="All checks passed!", duration_seconds=0.5),
        CheckResult(name="ruff/format", passed=True, output="3 files already formatted", duration_seconds=0.3),
        CheckResult(name="ty/check", passed=True, output="0 diagnostics", duration_seconds=1.2),
        CheckResult(name="pytest", passed=True, output="11 passed in 1.2s", duration_seconds=3.1),
    ]
    return VerificationReport(
        task_id=task_id,
        timestamp="2026-05-06T10:00:00Z",
        checks=checks,
        all_passed=True,
        total_duration_seconds=5.1,
    )


class TestVerifyCaptureFlag:
    """Test that ydk verify run --capture saves files via save_report."""

    def test_capture_flag_creates_proof_files(self, tmp_path: Path) -> None:
        """Simulate what --capture does: create ProofCapture, save report."""
        proof_dir = tmp_path / ".ydk" / "proofs" / "T-test"
        pc = ProofCapture(proof_dir)
        report = _make_report("T-test")
        artifacts = pc.save_report(report)

        plugins_dir = proof_dir / "plugins"
        assert plugins_dir.is_dir()
        assert (plugins_dir / "ruff_check.txt").exists()
        assert (plugins_dir / "ruff_format.txt").exists()
        assert (plugins_dir / "ty_check.txt").exists()
        assert (plugins_dir / "pytest.txt").exists()
        assert (proof_dir / "verification-report.json").exists()
        assert artifacts.verification_report_path is not None


class TestTaskDoneProofCapture:
    """Test that task done uses proof capture for PR body."""

    def test_done_uses_pr_body_builder(self, tmp_path: Path) -> None:
        """Verify PRBodyBuilder reads proof files correctly for task done."""
        proof_dir = tmp_path / ".ydk" / "proofs" / "T-001"
        pc = ProofCapture(proof_dir)
        pc.write_summary("T-001", "Implemented the widget system.")

        report = _make_report()
        pc.save_report(report)

        # Build PR body from proof files
        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)

        assert "## Summary" in body
        assert "Implemented the widget system." in body
        assert "### Verification Plugins" in body
        assert "ruff check" in body
        assert "All checks passed!" in body
        assert "pytest" in body
        assert "11 passed" in body
        assert "Generated with [YDK]" in body

    def test_done_with_summary_flag(self, tmp_path: Path) -> None:
        """Verify --summary flag writes summary.md before PR body build."""
        proof_dir = tmp_path / ".ydk" / "proofs" / "T-002"
        proof_dir.mkdir(parents=True)

        pc = ProofCapture(proof_dir)
        pc.write_summary("T-002", "Agent narrative here.")

        assert (proof_dir / "summary.md").exists()
        assert "Agent narrative" in (proof_dir / "summary.md").read_text()

        builder = PRBodyBuilder()
        body = builder.build("T-002", proof_dir)
        assert "Agent narrative here." in body

    def test_pr_body_includes_all_plugins(self, tmp_path: Path) -> None:
        """Verify all plugin outputs appear in PR body."""
        proof_dir = tmp_path / ".ydk" / "proofs" / "T-003"
        pc = ProofCapture(proof_dir)

        checks = [
            CheckResult(name="ruff/check", passed=True, output="clean", duration_seconds=0.2),
            CheckResult(name="custom/security-scan", passed=True, output="No vulnerabilities", duration_seconds=5.0),
            CheckResult(name="pytest", passed=True, output="42 passed in 8.0s", duration_seconds=8.0),
        ]
        report = VerificationReport(
            task_id="T-003",
            timestamp="2026-05-06T10:00:00Z",
            checks=checks,
            all_passed=True,
            total_duration_seconds=13.2,
        )
        pc.save_report(report)

        builder = PRBodyBuilder()
        body = builder.build("T-003", proof_dir)

        assert "ruff check" in body
        assert "custom security scan" in body
        assert "pytest" in body
        assert "No vulnerabilities" in body
        assert "42 passed" in body

    def test_check_status_from_report(self, tmp_path: Path) -> None:
        """Verify check_status reads the JSON report correctly."""
        proof_dir = tmp_path / ".ydk" / "proofs" / "T-004"
        pc = ProofCapture(proof_dir)

        checks = [
            CheckResult(name="ruff/check", passed=True, output="ok", duration_seconds=0.1),
            CheckResult(name="pytest", passed=False, output="2 failed", duration_seconds=3.0),
        ]
        report = VerificationReport(
            task_id="T-004",
            timestamp="2026-05-06T10:00:00Z",
            checks=checks,
            all_passed=False,
            total_duration_seconds=3.1,
        )
        pc.save_report(report)

        status = ProofCapture.check_status(proof_dir)
        assert status.all_passed is False
        assert "pytest" in status.failed_checks
        assert "ruff/check" not in status.failed_checks

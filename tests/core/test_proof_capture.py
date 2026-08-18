"""Tests for ProofCapture — deterministic proof file generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ydk.core.proof_capture import ProofCapture
from ydk.models.verification import CheckResult, VerificationReport


@pytest.fixture
def proof_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".ydk" / "proofs" / "T-001"
    return d


def _make_report(task_id: str = "T-001", checks: list[CheckResult] | None = None) -> VerificationReport:
    """Helper to build a VerificationReport for tests."""
    if checks is None:
        checks = [
            CheckResult(name="ruff/check", passed=True, output="All checks passed!", duration_seconds=0.5),
            CheckResult(name="ruff/format", passed=True, output="3 files formatted", duration_seconds=0.3),
            CheckResult(name="ty/check", passed=True, output="0 diagnostics", duration_seconds=1.2),
            CheckResult(name="pytest", passed=True, output="11 passed in 1.2s", duration_seconds=3.1),
        ]
    total = sum(c.duration_seconds for c in checks)
    all_passed = all(c.passed for c in checks)
    return VerificationReport(
        task_id=task_id,
        timestamp="2026-05-06T10:00:00Z",
        checks=checks,
        all_passed=all_passed,
        total_duration_seconds=total,
    )


class TestCaptureCommand:
    def test_captures_stdout_to_file(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        path = pc.capture_command("echo-test", ["echo", "hello world"])
        assert path.exists()
        assert "hello world" in path.read_text()

    def test_captures_stderr_to_file(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        path = pc.capture_command(
            "stderr-test",
            ["python3", "-c", "import sys; sys.stderr.write('err msg')"],
        )
        assert "err msg" in path.read_text()

    def test_returns_correct_path(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        path = pc.capture_command("my-check", ["echo", "ok"])
        assert path.name == "my-check.txt"
        assert path.parent == proof_dir

    def test_cwd_is_respected(self, proof_dir: Path, tmp_path: Path) -> None:
        pc = ProofCapture(proof_dir)
        path = pc.capture_command("pwd-test", ["pwd"], cwd=tmp_path)
        content = path.read_text().strip()
        assert Path(content).resolve() == tmp_path.resolve()


class TestSaveReport:
    def test_creates_plugin_files(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        report = _make_report()
        artifacts = pc.save_report(report)

        plugins_dir = proof_dir / "plugins"
        assert plugins_dir.is_dir()
        assert (plugins_dir / "ruff_check.txt").exists()
        assert (plugins_dir / "ruff_format.txt").exists()
        assert (plugins_dir / "ty_check.txt").exists()
        assert (plugins_dir / "pytest.txt").exists()
        assert len(artifacts.plugin_outputs) == 4

    def test_creates_json_report(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        report = _make_report()
        artifacts = pc.save_report(report)

        assert artifacts.verification_report_path is not None
        assert artifacts.verification_report_path.exists()
        data = json.loads(artifacts.verification_report_path.read_text())
        assert data["all_passed"] is True
        assert len(data["checks"]) == 4

    def test_plugin_file_content_has_status_line(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        report = _make_report()
        pc.save_report(report)

        content = (proof_dir / "plugins" / "ruff_check.txt").read_text()
        assert content.startswith("PASSED (0.5s)")
        assert "All checks passed!" in content

    def test_failed_check_content(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        checks = [
            CheckResult(name="pytest", passed=False, output="1 failed, 4 passed", duration_seconds=2.0),
        ]
        report = _make_report(checks=checks)
        pc.save_report(report)

        content = (proof_dir / "plugins" / "pytest.txt").read_text()
        assert content.startswith("FAILED (2.0s)")
        assert "1 failed, 4 passed" in content

    def test_task_id_from_report(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        report = _make_report(task_id="T-042")
        artifacts = pc.save_report(report)
        assert artifacts.task_id == "T-042"

    def test_task_id_falls_back_to_dir_name(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        report = _make_report(task_id=None)  # type: ignore[arg-type]
        # task_id=None in report → falls back to proof_dir.name
        artifacts = pc.save_report(report)
        assert artifacts.task_id == "T-001"

    def test_summary_path_included_when_exists(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        pc.write_summary("T-001", "Agent summary here.")
        report = _make_report()
        artifacts = pc.save_report(report)
        assert artifacts.summary_path is not None
        assert artifacts.summary_path.exists()

    def test_summary_path_none_when_missing(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        report = _make_report()
        artifacts = pc.save_report(report)
        assert artifacts.summary_path is None


class TestCheckStatus:
    def test_all_passed(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        report = _make_report()
        pc.save_report(report)

        status = ProofCapture.check_status(proof_dir)
        assert status.all_passed is True
        assert status.failed_checks == []

    def test_detects_failures(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        checks = [
            CheckResult(name="ruff/check", passed=True, output="ok", duration_seconds=0.1),
            CheckResult(name="pytest", passed=False, output="1 failed", duration_seconds=2.0),
        ]
        report = _make_report(checks=checks)
        pc.save_report(report)

        status = ProofCapture.check_status(proof_dir)
        assert status.all_passed is False
        assert "pytest" in status.failed_checks

    def test_missing_report_is_failure(self, proof_dir: Path) -> None:
        proof_dir.mkdir(parents=True, exist_ok=True)
        status = ProofCapture.check_status(proof_dir)
        assert status.all_passed is False
        assert "No verification report found" in status.failed_checks


class TestWriteSummary:
    def test_writes_summary_file(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        path = pc.write_summary("T-001", "This is the agent summary.")
        assert path.exists()
        assert path.read_text() == "This is the agent summary."
        assert path.name == "summary.md"


class TestListScreenshots:
    def test_returns_empty_when_no_screenshots_dir(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        assert pc.list_screenshots("T-001") == []

    def test_lists_image_files(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        ss_dir = proof_dir / "screenshots"
        ss_dir.mkdir(parents=True)
        (ss_dir / "dashboard.png").write_text("fake")
        (ss_dir / "order-form.jpg").write_text("fake")
        (ss_dir / "not-an-image.txt").write_text("fake")

        result = pc.list_screenshots("T-001")
        assert len(result) == 2
        names = [p.name for p in result]
        assert "dashboard.png" in names
        assert "order-form.jpg" in names


class TestListVideos:
    def test_returns_empty_when_no_videos(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        assert pc.list_videos("T-001") == []

    def test_lists_video_files(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        (proof_dir / "session.webm").write_text("fake")
        (proof_dir / "clip.mp4").write_text("fake")
        (proof_dir / "not-a-video.txt").write_text("fake")

        result = pc.list_videos("T-001")
        assert len(result) == 2
        names = [p.name for p in result]
        assert "session.webm" in names
        assert "clip.mp4" in names


class TestCapturePlugin:
    def test_saves_plugin_output_to_plugins_dir(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        path = pc.capture_plugin("lint-ruff", ["echo", "All checks passed"])
        assert path.exists()
        assert path.parent.name == "plugins"
        assert "All checks passed" in path.read_text()
        assert path.name == "lint-ruff.txt"

    def test_creates_plugins_dir(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        plugins_dir = proof_dir / "plugins"
        assert not plugins_dir.exists()
        pc.capture_plugin("test-plugin", ["echo", "ok"])
        assert plugins_dir.is_dir()


class TestSaveReview:
    def test_saves_review_to_reviews_dir(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        path = pc.save_review("claude-review", "Score: 8/10\nGood implementation.")
        assert path.exists()
        assert path.parent.name == "reviews"
        assert "Score: 8/10" in path.read_text()
        assert path.name == "claude-review.txt"

    def test_creates_reviews_dir(self, proof_dir: Path) -> None:
        pc = ProofCapture(proof_dir)
        reviews_dir = proof_dir / "reviews"
        assert not reviews_dir.exists()
        pc.save_review("reviewer-x", "content")
        assert reviews_dir.is_dir()

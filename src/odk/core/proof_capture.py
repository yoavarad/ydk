"""Deterministic proof capture — saves verification report output to files.

The key principle: proof files are produced by the verification pipeline,
not by re-running hardcoded commands.  The agent contributes only ``summary.md``.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from odk.models.proof import ProofArtifacts, ProofStatus

if TYPE_CHECKING:
    from pathlib import Path

    from odk.models.verification import VerificationReport


class ProofCapture:
    """Capture verification command output to proof files."""

    def __init__(self, proof_dir: Path) -> None:
        self._proof_dir = proof_dir
        self._proof_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Low-level: run any command, capture output
    # ------------------------------------------------------------------

    def capture_command(self, name: str, command: list[str], *, cwd: Path | None = None) -> Path:
        """Run *command*, write combined stdout+stderr to ``{name}.txt``, return the path."""
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd else None,
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr if output else result.stderr

        out_path = self._proof_dir / f"{name}.txt"
        out_path.write_text(output)
        return out_path

    # ------------------------------------------------------------------
    # High-level: save a full verification report
    # ------------------------------------------------------------------

    def save_report(self, report: VerificationReport) -> ProofArtifacts:
        """Save the full verification report as proof files.

        Each plugin's output becomes a separate file in plugins/.
        The full report is also saved as JSON for machine consumption.
        """
        plugins_dir = self._proof_dir / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)

        plugin_outputs: dict[str, Path] = {}
        for check in report.checks:
            safe_name = check.name.replace("/", "_").replace(" ", "_")
            out_path = plugins_dir / f"{safe_name}.txt"
            status_line = f"{'PASSED' if check.passed else 'FAILED'} ({check.duration_seconds}s)"
            content = f"{status_line}\n\n{check.output}"
            out_path.write_text(content)
            plugin_outputs[check.name] = out_path

        # Save the full report as JSON
        report_path = self._proof_dir / "verification-report.json"
        report_path.write_text(report.model_dump_json(indent=2))

        task_id = report.task_id or self._proof_dir.name

        return ProofArtifacts(
            task_id=task_id,
            verification_report_path=report_path,
            plugin_outputs=plugin_outputs,
            screenshots=self.list_screenshots(task_id),
            videos=self.list_videos(task_id),
            summary_path=self._proof_dir / "summary.md" if (self._proof_dir / "summary.md").exists() else None,
        )

    # ------------------------------------------------------------------
    # Plugin and review capture
    # ------------------------------------------------------------------

    def capture_plugin(self, plugin_name: str, command: list[str], *, cwd: Path | None = None) -> Path:
        """Run a verification plugin and save output to ``plugins/{plugin_name}.txt``."""
        plugins_dir = self._proof_dir / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd else None,
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr if output else result.stderr

        out_path = plugins_dir / f"{plugin_name}.txt"
        out_path.write_text(output)
        return out_path

    def save_review(self, reviewer_id: str, content: str) -> Path:
        """Save an AI review result to ``reviews/{reviewer_id}.txt``."""
        reviews_dir = self._proof_dir / "reviews"
        reviews_dir.mkdir(parents=True, exist_ok=True)
        out_path = reviews_dir / f"{reviewer_id}.txt"
        out_path.write_text(content)
        return out_path

    # ------------------------------------------------------------------
    # Summary (agent-authored)
    # ------------------------------------------------------------------

    def write_summary(self, task_id: str, summary: str) -> Path:
        """Write the agent-authored summary to ``summary.md``."""
        path = self._proof_dir / "summary.md"
        path.write_text(summary)
        return path

    # ------------------------------------------------------------------
    # Media listing
    # ------------------------------------------------------------------

    def list_screenshots(self, task_id: str) -> list[Path]:
        """List screenshot images in the proof directory."""
        screenshots_dir = self._proof_dir / "screenshots"
        if not screenshots_dir.is_dir():
            return []
        extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        return sorted(p for p in screenshots_dir.iterdir() if p.suffix.lower() in extensions)

    def list_videos(self, task_id: str) -> list[Path]:
        """List video files in the proof directory."""
        extensions = {".webm", ".mp4", ".avi", ".mov"}
        return sorted(p for p in self._proof_dir.iterdir() if p.suffix.lower() in extensions)

    # ------------------------------------------------------------------
    # Status check
    # ------------------------------------------------------------------

    @staticmethod
    def check_status(proof_dir: Path) -> ProofStatus:
        """Read the verification report JSON and determine pass/fail.

        Falls back to scanning plugin files if no JSON report exists.
        """
        report_path = proof_dir / "verification-report.json"
        if not report_path.exists():
            return ProofStatus(all_passed=False, failed_checks=["No verification report found"])

        from odk.models.verification import VerificationReport

        report = VerificationReport.model_validate_json(report_path.read_text())
        failed = [c.name for c in report.checks if not c.passed]
        return ProofStatus(all_passed=report.all_passed, failed_checks=failed)

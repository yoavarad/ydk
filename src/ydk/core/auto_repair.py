"""Auto-repair loop for verification failures.

Runs verification, formats errors as structured JSON for the coding agent,
and supports retrying up to a configurable max count. YDK does NOT call an
LLM -- the coding agent (Claude Code) reads the structured output and fixes
the code itself.

Between retries, auto-fixable tools (ruff) are applied automatically.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from ydk.core.verifier import Verifier
    from ydk.models.verification import VerificationReport

logger = logging.getLogger("ydk.auto_repair")


class RepairResult(BaseModel):
    """Result of a repair loop run."""

    attempts: int
    final_passed: bool
    errors_per_attempt: list[str]


class RepairLoop:
    """Runs verification in a retry loop with structured error output.

    Between each attempt the loop applies automatic fixes (ruff check --fix,
    ruff format) and then re-runs verification. The structured error JSON is
    recorded so the coding agent can parse remaining failures.
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self._root = project_root or Path(".")

    def format_errors(self, report: VerificationReport) -> str:
        """Produce a structured, agent-readable error summary as JSON.

        Returns a JSON string with the shape::

            {
                "all_passed": false,
                "failed_checks": [
                    {"name": "lint", "output": "...", "duration_seconds": 0.2}
                ]
            }
        """
        failed_checks: list[dict[str, Any]] = []
        for check in report.checks:
            if not check.passed:
                entry: dict[str, Any] = {
                    "name": check.name,
                    "output": check.output,
                    "duration_seconds": check.duration_seconds,
                }
                if check.detail:
                    entry["detail"] = check.detail
                failed_checks.append(entry)

        return json.dumps(
            {"all_passed": report.all_passed, "failed_checks": failed_checks},
            indent=2,
        )

    def _apply_auto_fixes(self, report: VerificationReport) -> None:
        """Apply automatic fixes between retries.

        Currently supports:
        - ruff check --fix (lint auto-fixes)
        - ruff format (formatting)
        """
        # Check if any lint-related check failed
        lint_failed = any(not check.passed and check.name in ("lint", "ruff", "ruff-check") for check in report.checks)
        format_failed = any(not check.passed and check.name in ("format", "ruff-format") for check in report.checks)

        if lint_failed:
            try:
                subprocess.run(
                    ["ruff", "check", "--fix", "."],
                    capture_output=True,
                    text=True,
                    cwd=str(self._root),
                    timeout=60,
                )
                logger.info("Applied ruff check --fix")
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        if format_failed or lint_failed:
            try:
                subprocess.run(
                    ["ruff", "format", "."],
                    capture_output=True,
                    text=True,
                    cwd=str(self._root),
                    timeout=60,
                )
                logger.info("Applied ruff format")
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

    async def run(
        self,
        verifier: Verifier,
        max_retries: int = 3,
        *,
        trigger: str = "pre-push",
        context: dict[str, Any] | None = None,
    ) -> RepairResult:
        """Run verification up to *max_retries* times.

        On each failure, applies auto-fixes (ruff) and records the structured
        error JSON in ``errors_per_attempt``. Stops early on success.
        """
        errors: list[str] = []

        for attempt in range(1, max_retries + 1):
            if context is not None:
                report = await verifier.run_all(trigger=trigger, context=context)
            else:
                report = await verifier.run_all(trigger=trigger)

            if report.all_passed:
                return RepairResult(
                    attempts=attempt,
                    final_passed=True,
                    errors_per_attempt=errors,
                )

            # Record structured errors for this attempt
            errors.append(self.format_errors(report))

            # Apply auto-fixes before retrying (skip on last attempt)
            if attempt < max_retries:
                self._apply_auto_fixes(report)

        return RepairResult(
            attempts=max_retries,
            final_passed=False,
            errors_per_attempt=errors,
        )

"""Check external gate conditions."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime

from ydk.models.gate import Gate, GateStatus, GateType


class GateChecker:
    """Evaluate external gate conditions."""

    def check_gate(self, gate: Gate) -> GateStatus:
        """Check if a gate condition is met."""
        if gate.status in {GateStatus.RESOLVED, GateStatus.FAILED}:
            return gate.status
        if gate.type == GateType.PR_MERGED:
            return GateStatus.RESOLVED if self.check_pr_merged(gate.config.get("pr_url", "")) else GateStatus.PENDING
        if gate.type == GateType.CI_PASSED:
            return GateStatus.RESOLVED if self.check_ci_passed(gate.config.get("run_url", "")) else GateStatus.PENDING
        if gate.type == GateType.TIMER:
            created_at = gate.config.get("created_at", "")
            duration = int(gate.config.get("duration_minutes", "0"))
            return GateStatus.RESOLVED if self.check_timer(created_at, duration) else GateStatus.PENDING
        if gate.type == GateType.HUMAN:
            return GateStatus.RESOLVED if self.check_human(gate.id) else GateStatus.PENDING
        return GateStatus.PENDING

    def check_pr_merged(self, pr_url: str) -> bool:
        """Check if a GitHub PR is merged."""
        result = subprocess.run(
            ["gh", "pr", "view", pr_url, "--json", "state", "--jq", ".state"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False
        return result.stdout.strip() == "MERGED"

    def check_ci_passed(self, run_url: str) -> bool:
        """Check if a GitHub Actions run passed."""
        result = subprocess.run(
            [
                "gh",
                "run",
                "view",
                run_url,
                "--json",
                "status,conclusion",
                "--jq",
                "[.status, .conclusion] | @tsv",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False
        parts = result.stdout.strip().split("\t")
        return len(parts) >= 2 and parts[0] == "completed" and parts[1] == "success"

    def check_timer(self, created_at: str, duration_minutes: int) -> bool:
        """Check if timer duration has elapsed."""
        try:
            start = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        except (ValueError, TypeError):
            return False
        elapsed = (datetime.now(UTC) - start).total_seconds()
        return elapsed >= duration_minutes * 60

    def check_human(self, gate_id: str) -> bool:
        """Human gates are never auto-resolved."""
        return False

    def resolve_gate(self, gate: Gate) -> Gate:
        """Manually resolve a gate."""
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return gate.model_copy(update={"status": GateStatus.RESOLVED, "resolved_at": now})

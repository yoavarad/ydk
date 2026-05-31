"""Rich Live displays for parallel agent evaluations and progress tracking."""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING

from rich.table import Table

from odk.output.console import console

if TYPE_CHECKING:
    from odk.models.evaluation import CriterionResult


@dataclass
class AgentStatus:
    """Tracks the evaluation state of a single agent."""

    agent_id: str
    agent_name: str
    group: str
    status: str = "PENDING"  # PENDING, RUNNING, DONE, FAILED
    score: float | None = None
    threshold: int = 8
    start_time: float | None = None
    end_time: float | None = None

    @property
    def elapsed(self) -> str:
        """Return formatted elapsed time string."""
        if self.start_time is None:
            return "—"
        end = self.end_time or time.time()
        return f"{end - self.start_time:.1f}s"


_STATUS_ICONS: dict[str, str] = {
    "PENDING": "⏳",
    "RUNNING": "▶️",
    "DONE": "✅",
    "FAILED": "❌",
}


class LiveAgentDisplay:
    """Thread-safe live display for parallel agent evaluations."""

    def __init__(self, agents: list[tuple[str, str, str, int]]) -> None:
        """Initialize with agent tuples: (id, name, group, threshold)."""
        self.statuses: dict[str, AgentStatus] = {}
        self._lock = Lock()
        for agent_id, name, group, threshold in agents:
            self.statuses[agent_id] = AgentStatus(
                agent_id=agent_id,
                agent_name=name,
                group=group,
                threshold=threshold,
            )

    def update(self, agent_id: str, status: str, score: float | None = None) -> None:
        """Thread-safe status update."""
        with self._lock:
            agent = self.statuses[agent_id]
            agent.status = status
            if status == "RUNNING" and agent.start_time is None:
                agent.start_time = time.time()
            if status in ("DONE", "FAILED"):
                agent.end_time = time.time()
            if score is not None:
                agent.score = score

    def build_table(self, title: str = "Evaluation") -> Table:
        """Build Rich table showing current status."""
        done_count = sum(1 for s in self.statuses.values() if s.status in ("DONE", "FAILED"))
        total = len(self.statuses)

        table = Table(title=f"{title} [{done_count}/{total}]")
        table.add_column("Agent", style="cyan")
        table.add_column("Group", style="magenta")
        table.add_column("Status")
        table.add_column("Time", justify="right")
        table.add_column("Score", justify="right")
        table.add_column("Result")

        for agent in self.statuses.values():
            icon = _STATUS_ICONS.get(agent.status, "?")
            score_str = f"{agent.score:.1f}" if agent.score is not None else "—"
            result = ("✅ PASS" if agent.score >= agent.threshold else "❌ FAIL") if agent.score is not None else "—"
            table.add_row(
                agent.agent_name,
                agent.group,
                f"{icon} {agent.status}",
                agent.elapsed,
                score_str,
                result,
            )
        return table

    def summary(self, results: list[CriterionResult]) -> bool:
        """Print pass/fail summary. Returns True if all passed."""
        all_passed = all(r.passed for r in results)
        if all_passed:
            console.print("[bold green]ALL CRITERIA PASSED[/bold green]")
        else:
            failed = [r for r in results if not r.passed]
            console.print(f"[bold red]{len(failed)} CRITERIA FAILED[/bold red]")
            for r in failed:
                console.print(f"  [red]• {r.criterion_id}: {r.score:.1f} — {r.reasoning}[/red]")
        return all_passed

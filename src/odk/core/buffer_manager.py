"""Buffer management — Critical Chain sprint health tracking."""

from __future__ import annotations

from typing import TYPE_CHECKING

from odk.models.buffer import BufferStatus, BufferZone

if TYPE_CHECKING:
    from odk.models.pm import TaskSummary


class BufferManager:
    """Calculate sprint buffer consumption and health zone."""

    def calculate_status(
        self,
        tasks: list[TaskSummary],
        planned_waves: int | None = None,
    ) -> BufferStatus:
        """Compute buffer status from task list and optional wave count."""
        total = len(tasks)
        done = sum(1 for t in tasks if t.status == "done")
        in_progress = sum(1 for t in tasks if t.status == "in-progress")
        blocked = sum(1 for t in tasks if t.status.startswith("blocked"))

        effective_waves = planned_waves if planned_waves is not None else max(total, 1)

        # Elapsed waves estimated from proportion of completed tasks
        elapsed = round(done / total * effective_waves) if total > 0 else 0

        # Buffer consumption: how much of the timeline has been used
        consumption = elapsed / effective_waves if effective_waves > 0 and total > 0 else 0.0

        # Sprint complete — always green regardless of consumption
        all_done = total > 0 and done == total
        zone = BufferZone.GREEN if all_done else _classify_zone(consumption)

        # On track: completion percentage >= elapsed percentage
        completion_pct = done / total if total > 0 else 1.0
        elapsed_pct = elapsed / effective_waves if effective_waves > 0 else 0.0
        on_track = completion_pct >= elapsed_pct

        summary = _build_summary(total, done, zone, consumption)

        return BufferStatus(
            total_tasks=total,
            completed_tasks=done,
            in_progress_tasks=in_progress,
            blocked_tasks=blocked,
            planned_waves=effective_waves,
            elapsed_waves=elapsed,
            buffer_consumption_pct=consumption,
            zone=zone,
            on_track=on_track,
            summary=summary,
        )


def _classify_zone(consumption: float) -> BufferZone:
    """Map consumption percentage to a buffer zone."""
    if consumption < 0.33:
        return BufferZone.GREEN
    if consumption < 0.66:
        return BufferZone.YELLOW
    return BufferZone.RED


def _build_summary(total: int, done: int, zone: BufferZone, consumption: float) -> str:
    """Build a human-readable status line."""
    if total == 0:
        return "No tasks in sprint."
    pct = round(consumption * 100)
    return f"{done}/{total} tasks done | Buffer {pct}% consumed | Zone: {zone.value.upper()}"

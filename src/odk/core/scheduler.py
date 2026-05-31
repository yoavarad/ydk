"""Resource-constrained scheduling with critical chain analysis.

Uses topological sort (Kahn's algorithm) as foundation, then assigns tasks
to agent slots greedily: the earliest available agent gets the highest-priority
ready task.  Computes total duration, critical chain (longest path considering
resource constraints), and utilization per agent.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from odk.models.schedule import Schedule, ScheduleSlot

if TYPE_CHECKING:
    from odk.models.task import Task


class Scheduler:
    """Produce resource-constrained schedules for task DAGs."""

    def schedule(self, tasks: list[Task], num_agents: int) -> Schedule:
        """Schedule *tasks* across *num_agents* agent slots.

        Returns a :class:`Schedule` with slot assignments, total waves,
        critical chain, and per-agent utilization.
        """
        if not tasks:
            return Schedule(
                slots=[],
                total_waves=0,
                critical_chain=[],
                agent_utilization={},
            )

        task_map = {t.id: t for t in tasks}
        task_ids = set(task_map)

        # Build adjacency (dep -> dependents) and in-degree.
        adj: dict[str, list[str]] = defaultdict(list)
        in_degree: dict[str, int] = {tid: 0 for tid in task_ids}
        for t in tasks:
            for dep_id in t.blocking_dep_ids():
                if dep_id in task_ids:
                    adj[dep_id].append(t.id)
                    in_degree[t.id] += 1

        # Kahn's algorithm with resource constraint.
        ready: list[str] = sorted(tid for tid, deg in in_degree.items() if deg == 0)
        slots: list[ScheduleSlot] = []
        task_wave: dict[str, int] = {}
        wave = 0

        while ready:
            # Assign up to num_agents tasks from the ready queue this wave.
            assigned = ready[:num_agents]
            remaining = ready[num_agents:]

            for idx, tid in enumerate(assigned):
                slots.append(ScheduleSlot(task_id=tid, agent=idx, wave=wave))
                task_wave[tid] = wave

            # Collect newly ready tasks after this wave completes.
            newly_ready: list[str] = []
            for tid in assigned:
                for neighbor in sorted(adj[tid]):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        newly_ready.append(neighbor)

            ready = sorted(remaining + newly_ready)
            wave += 1

        total_waves = wave

        # Compute critical chain (longest path through the scheduled waves).
        critical_chain = self._compute_critical_chain(task_wave, adj, task_ids, slots)

        # Compute utilization.
        agent_utilization = self._compute_utilization(slots, num_agents, total_waves)

        return Schedule(
            slots=slots,
            total_waves=total_waves,
            critical_chain=critical_chain,
            agent_utilization=agent_utilization,
        )

    def critical_chain(self, tasks: list[Task], num_agents: int) -> list[str]:
        """Return task IDs on the critical chain."""
        return self.schedule(tasks, num_agents).critical_chain

    def estimate_duration(self, tasks: list[Task], num_agents: int) -> int:
        """Return total waves needed."""
        return self.schedule(tasks, num_agents).total_waves

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_critical_chain(
        task_wave: dict[str, int],
        adj: dict[str, list[str]],
        task_ids: set[str],
        slots: list[ScheduleSlot] | None = None,
    ) -> list[str]:
        """Find the longest path through the scheduled DAG.

        Includes both dependency edges and resource contention edges
        (same agent, consecutive waves) — this is what makes it a
        *critical chain* rather than just a critical path.
        """
        if not task_ids:
            return []

        # Build a combined adjacency list: DAG edges + resource edges.
        combined_adj: dict[str, list[str]] = defaultdict(list)
        for node, neighbors in adj.items():
            combined_adj[node].extend(neighbors)

        # Add resource contention edges: same agent, consecutive tasks.
        if slots:
            agent_schedule: dict[int, list[ScheduleSlot]] = defaultdict(list)
            for slot in slots:
                agent_schedule[slot.agent].append(slot)
            for agent_slots in agent_schedule.values():
                ordered = sorted(agent_slots, key=lambda s: s.wave)
                for i in range(len(ordered) - 1):
                    src = ordered[i].task_id
                    dst = ordered[i + 1].task_id
                    if dst not in combined_adj[src]:
                        combined_adj[src].append(dst)

        # Topological order by wave then alphabetical for determinism.
        topo = sorted(task_ids, key=lambda tid: (task_wave[tid], tid))

        # Longest-path DP tracking both wave-span and node-count.
        # dist = (wave_span, node_count) — wave_span is primary,
        # node_count breaks ties to prefer paths with more tasks.
        dist: dict[str, tuple[int, int]] = {tid: (1, 1) for tid in task_ids}
        predecessor: dict[str, str | None] = {tid: None for tid in task_ids}

        for node in topo:
            for neighbor in combined_adj[node]:
                wave_span = task_wave[neighbor] - task_wave[node] + dist[node][0]
                node_count = dist[node][1] + 1
                if (wave_span, node_count) > dist[neighbor]:
                    dist[neighbor] = (wave_span, node_count)
                    predecessor[neighbor] = node

        # Trace back from the node with the longest path.
        end_node = max(sorted(dist), key=lambda n: dist[n])
        chain: list[str] = []
        current: str | None = end_node
        while current is not None:
            chain.append(current)
            current = predecessor[current]
        chain.reverse()
        return chain

    @staticmethod
    def _compute_utilization(
        slots: list[ScheduleSlot],
        num_agents: int,
        total_waves: int,
    ) -> dict[int, float]:
        """Compute per-agent utilization as fraction of total waves."""
        if total_waves == 0:
            return {}

        agent_tasks: dict[int, int] = defaultdict(int)
        for slot in slots:
            agent_tasks[slot.agent] += 1

        return {agent: agent_tasks.get(agent, 0) / total_waves for agent in range(num_agents)}

"""Tests for odk.core.scheduler — resource-constrained scheduling."""

from odk.core.scheduler import Scheduler
from odk.models.schedule import Schedule, ScheduleSlot
from odk.models.task import Task


class TestScheduleSingleAgent:
    """With 1 agent, schedule should be purely sequential (topological order)."""

    def test_single_agent_linear_chain(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B", depends_on=["T-001"]),
            Task(id="T-003", title="C", depends_on=["T-002"]),
        ]
        scheduler = Scheduler()
        result = scheduler.schedule(tasks, num_agents=1)

        assert result.total_waves == 3
        assert len(result.slots) == 3
        # Each task on agent 0, waves 0, 1, 2
        for slot in result.slots:
            assert slot.agent == 0

    def test_single_agent_parallel_tasks_become_sequential(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B"),
            Task(id="T-003", title="C"),
        ]
        scheduler = Scheduler()
        result = scheduler.schedule(tasks, num_agents=1)

        assert result.total_waves == 3
        waves = [s.wave for s in result.slots]
        assert sorted(waves) == [0, 1, 2]


class TestScheduleUnlimitedAgents:
    """With unlimited agents (>= task count), schedule matches DAG parallel waves."""

    def test_unlimited_agents_all_parallel(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B"),
            Task(id="T-003", title="C"),
        ]
        scheduler = Scheduler()
        result = scheduler.schedule(tasks, num_agents=10)

        # All 3 tasks should run in wave 0
        assert result.total_waves == 1
        for slot in result.slots:
            assert slot.wave == 0

    def test_unlimited_agents_with_deps(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B"),
            Task(id="T-003", title="C", depends_on=["T-001", "T-002"]),
        ]
        scheduler = Scheduler()
        result = scheduler.schedule(tasks, num_agents=10)

        assert result.total_waves == 2
        slot_map = {s.task_id: s for s in result.slots}
        assert slot_map["T-001"].wave == 0
        assert slot_map["T-002"].wave == 0
        assert slot_map["T-003"].wave == 1


class TestScheduleResourceConstrained:
    """Test scheduling with limited agents creating bottlenecks."""

    def test_two_agents_four_parallel_tasks(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B"),
            Task(id="T-003", title="C"),
            Task(id="T-004", title="D"),
        ]
        scheduler = Scheduler()
        result = scheduler.schedule(tasks, num_agents=2)

        assert result.total_waves == 2
        wave_0 = [s for s in result.slots if s.wave == 0]
        wave_1 = [s for s in result.slots if s.wave == 1]
        assert len(wave_0) == 2
        assert len(wave_1) == 2
        # Each wave should use both agents
        assert {s.agent for s in wave_0} == {0, 1}
        assert {s.agent for s in wave_1} == {0, 1}

    def test_bottleneck_with_deps(self) -> None:
        """Bottleneck: 4 tasks depend on 1, but only 2 agents."""
        tasks = [
            Task(id="T-001", title="Setup"),
            Task(id="T-002", title="A", depends_on=["T-001"]),
            Task(id="T-003", title="B", depends_on=["T-001"]),
            Task(id="T-004", title="C", depends_on=["T-001"]),
            Task(id="T-005", title="D", depends_on=["T-001"]),
        ]
        scheduler = Scheduler()
        result = scheduler.schedule(tasks, num_agents=2)

        # Wave 0: T-001 (only 1 task ready)
        # Wave 1: T-002, T-003 (2 agents, 4 tasks ready)
        # Wave 2: T-004, T-005
        assert result.total_waves == 3

    def test_methodology_example_two_agents(self) -> None:
        """Methodology example with 2 agents."""
        tasks = [
            Task(id="T01", title="Project setup"),
            Task(id="T02", title="Data model", depends_on=["T01"]),
            Task(id="T03", title="API routes", depends_on=["T01"]),
            Task(id="T04", title="Business logic", depends_on=["T02", "T03"]),
            Task(id="T05", title="Integration", depends_on=["T04"]),
            Task(id="T06", title="Notifications", depends_on=["T04"]),
            Task(id="T07", title="E2E tests", depends_on=["T05", "T06"]),
        ]
        scheduler = Scheduler()
        result = scheduler.schedule(tasks, num_agents=2)

        # With 2 agents:
        # Wave 0: T01
        # Wave 1: T02, T03 (both fit in 2 agents)
        # Wave 2: T04
        # Wave 3: T05, T06 (both fit)
        # Wave 4: T07
        assert result.total_waves == 5


class TestCriticalChain:
    """Test critical chain identification under resource constraints."""

    def test_critical_chain_linear(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B", depends_on=["T-001"]),
            Task(id="T-003", title="C", depends_on=["T-002"]),
        ]
        scheduler = Scheduler()
        chain = scheduler.critical_chain(tasks, num_agents=1)
        assert chain == ["T-001", "T-002", "T-003"]

    def test_critical_chain_resource_bottleneck(self) -> None:
        """With 1 agent, independent tasks extend the critical chain."""
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B"),
            Task(id="T-003", title="C", depends_on=["T-001", "T-002"]),
        ]
        scheduler = Scheduler()
        chain = scheduler.critical_chain(tasks, num_agents=1)

        # With 1 agent: T-001 wave 0, T-002 wave 1, T-003 wave 2
        # Critical chain = longest chain through the schedule
        assert len(chain) == 3
        assert chain[-1] == "T-003"

    def test_critical_chain_with_unlimited_agents(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B"),
            Task(id="T-003", title="C", depends_on=["T-001", "T-002"]),
        ]
        scheduler = Scheduler()
        chain = scheduler.critical_chain(tasks, num_agents=10)

        # With unlimited agents: T-001 and T-002 in wave 0, T-003 in wave 1
        # Critical chain: one of {T-001, T-002} -> T-003
        assert len(chain) == 2
        assert chain[-1] == "T-003"


class TestUtilization:
    """Test agent utilization calculation."""

    def test_full_utilization(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B"),
        ]
        scheduler = Scheduler()
        result = scheduler.schedule(tasks, num_agents=1)

        assert result.agent_utilization[0] == 1.0

    def test_partial_utilization(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B"),
            Task(id="T-003", title="C"),
        ]
        scheduler = Scheduler()
        result = scheduler.schedule(tasks, num_agents=2)

        # 2 waves, agent 0 does 2 tasks, agent 1 does 1 task
        assert result.agent_utilization[0] == 1.0
        assert result.agent_utilization[1] == 0.5

    def test_utilization_with_idle_agents(self) -> None:
        """10 agents but only 2 tasks — most agents idle."""
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B"),
        ]
        scheduler = Scheduler()
        result = scheduler.schedule(tasks, num_agents=10)

        # 1 wave, 2 agents used, 8 idle
        used = sum(1 for u in result.agent_utilization.values() if u > 0)
        assert used == 2
        idle = sum(1 for u in result.agent_utilization.values() if u == 0.0)
        assert idle == 8


class TestEstimateDuration:
    def test_estimate_matches_total_waves(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B"),
            Task(id="T-003", title="C"),
        ]
        scheduler = Scheduler()
        assert scheduler.estimate_duration(tasks, num_agents=1) == 3
        assert scheduler.estimate_duration(tasks, num_agents=3) == 1
        assert scheduler.estimate_duration(tasks, num_agents=2) == 2


class TestEdgeCases:
    def test_empty_tasks(self) -> None:
        scheduler = Scheduler()
        result = scheduler.schedule([], num_agents=2)
        assert result.total_waves == 0
        assert result.slots == []
        assert result.critical_chain == []
        assert result.agent_utilization == {}

    def test_single_task(self) -> None:
        tasks = [Task(id="T-001", title="A")]
        scheduler = Scheduler()
        result = scheduler.schedule(tasks, num_agents=5)
        assert result.total_waves == 1
        assert len(result.slots) == 1
        assert result.slots[0].agent == 0
        assert result.slots[0].wave == 0


class TestScheduleModel:
    """Test the Schedule model itself."""

    def test_schedule_slot_forbids_extra(self) -> None:
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="extra"):
            ScheduleSlot(task_id="T-001", agent=0, wave=0, extra="bad")  # type: ignore[call-arg]

    def test_schedule_forbids_extra(self) -> None:
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="extra"):
            Schedule(
                slots=[],
                total_waves=0,
                critical_chain=[],
                agent_utilization={},
                extra="bad",  # type: ignore[call-arg]
            )

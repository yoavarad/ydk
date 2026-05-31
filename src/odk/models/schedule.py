"""Models for resource-constrained scheduling."""

from pydantic import BaseModel, ConfigDict


class ScheduleSlot(BaseModel):
    """A single task assignment: which agent runs it in which time slot."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    agent: int  # Agent index (0 to num_agents-1)
    wave: int  # Time slot


class Schedule(BaseModel):
    """Complete resource-constrained schedule for a set of tasks."""

    model_config = ConfigDict(extra="forbid")

    slots: list[ScheduleSlot]
    total_waves: int
    critical_chain: list[str]  # Task IDs on the critical chain
    agent_utilization: dict[int, float]  # Agent index -> % utilized

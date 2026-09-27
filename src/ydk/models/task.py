"""Models for task management."""

from pydantic import BaseModel, ConfigDict, Field

from ydk.models.pm import BLOCKING_DEPENDENCY_TYPES, Dependency, DependencyType


class TaskDependency(BaseModel):
    """A typed dependency used in DAG validation."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    type: DependencyType = DependencyType.BLOCKS


def is_blocking_dependency(dep: str | Dependency | TaskDependency) -> bool:
    """Return True if *dep* creates an execution edge (gates readiness).

    Plain string dependencies are treated as ``blocks`` (legacy format).
    """
    return isinstance(dep, str) or dep.type in BLOCKING_DEPENDENCY_TYPES


class Task(BaseModel):
    """A single task node in the dependency DAG."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    depends_on: list[str | TaskDependency] = Field(default_factory=list)

    def blocking_dep_ids(self) -> list[str]:
        """Return task IDs of dependencies that create execution edges.

        Normalizes IDs by stripping leading ``#`` so GitHub issue refs
        like ``#829`` match task IDs stored as ``829``.
        """
        return [
            (dep if isinstance(dep, str) else dep.task_id).lstrip("#")
            for dep in self.depends_on
            if is_blocking_dependency(dep)
        ]


class DagValidationResult(BaseModel):
    """Result of validating the task dependency DAG for cycles and parallelism."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    error: str | None = None
    cycles: list[str] | None = None
    parallel_sets: list[list[str]]
    critical_path: list[str]
    critical_path_length: int
    fan_out: dict[str, int]

"""Tests for DAG validation with rich dependency types.

Only blocking types (blocks, conditional-blocks, waits-for) create execution edges.
Non-blocking types (validates, caused-by, discovered-from, supersedes, related) are metadata.
"""

from ydk.core.task_validator import validate_dag
from ydk.models.task import DependencyType, Task, TaskDependency


class TestDagBlockingTypes:
    def test_blocks_creates_execution_edge(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(
                id="T-002",
                title="B",
                depends_on=[
                    TaskDependency(task_id="T-001", type=DependencyType.BLOCKS),
                ],
            ),
        ]
        result = validate_dag(tasks)
        assert result.valid is True
        assert len(result.parallel_sets) == 2
        assert result.parallel_sets[0] == ["T-001"]
        assert result.parallel_sets[1] == ["T-002"]

    def test_conditional_blocks_creates_execution_edge(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(
                id="T-002",
                title="B",
                depends_on=[
                    TaskDependency(task_id="T-001", type=DependencyType.CONDITIONAL_BLOCKS),
                ],
            ),
        ]
        result = validate_dag(tasks)
        assert len(result.parallel_sets) == 2

    def test_waits_for_creates_execution_edge(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(
                id="T-002",
                title="B",
                depends_on=[
                    TaskDependency(task_id="T-001", type=DependencyType.WAITS_FOR),
                ],
            ),
        ]
        result = validate_dag(tasks)
        assert len(result.parallel_sets) == 2


class TestDagNonBlockingTypes:
    def test_validates_does_not_create_execution_edge(self) -> None:
        tasks = [
            Task(id="T-001", title="Feature"),
            Task(
                id="T-002",
                title="Test for feature",
                depends_on=[
                    TaskDependency(task_id="T-001", type=DependencyType.VALIDATES),
                ],
            ),
        ]
        result = validate_dag(tasks)
        assert result.valid is True
        assert len(result.parallel_sets) == 1
        assert sorted(result.parallel_sets[0]) == ["T-001", "T-002"]

    def test_caused_by_does_not_create_execution_edge(self) -> None:
        tasks = [
            Task(id="T-001", title="Root cause"),
            Task(
                id="T-002",
                title="Bug",
                depends_on=[
                    TaskDependency(task_id="T-001", type=DependencyType.CAUSED_BY),
                ],
            ),
        ]
        result = validate_dag(tasks)
        assert len(result.parallel_sets) == 1

    def test_discovered_from_does_not_create_execution_edge(self) -> None:
        tasks = [
            Task(id="T-001", title="Parent"),
            Task(
                id="T-002",
                title="Discovery",
                depends_on=[
                    TaskDependency(task_id="T-001", type=DependencyType.DISCOVERED_FROM),
                ],
            ),
        ]
        result = validate_dag(tasks)
        assert len(result.parallel_sets) == 1

    def test_supersedes_does_not_create_execution_edge(self) -> None:
        tasks = [
            Task(id="T-001", title="Old approach"),
            Task(
                id="T-002",
                title="New approach",
                depends_on=[
                    TaskDependency(task_id="T-001", type=DependencyType.SUPERSEDES),
                ],
            ),
        ]
        result = validate_dag(tasks)
        assert len(result.parallel_sets) == 1

    def test_related_does_not_create_execution_edge(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(
                id="T-002",
                title="B",
                depends_on=[
                    TaskDependency(task_id="T-001", type=DependencyType.RELATED),
                ],
            ),
        ]
        result = validate_dag(tasks)
        assert len(result.parallel_sets) == 1


class TestDagCycleDetectionWithTypes:
    def test_cycle_detected_with_blocking_types(self) -> None:
        tasks = [
            Task(
                id="T-001",
                title="A",
                depends_on=[
                    TaskDependency(task_id="T-002", type=DependencyType.BLOCKS),
                ],
            ),
            Task(
                id="T-002",
                title="B",
                depends_on=[
                    TaskDependency(task_id="T-001", type=DependencyType.BLOCKS),
                ],
            ),
        ]
        result = validate_dag(tasks)
        assert result.valid is False

    def test_cycle_ignored_for_non_blocking_types(self) -> None:
        """A 'validates' cycle should not fail DAG validation."""
        tasks = [
            Task(
                id="T-001",
                title="A",
                depends_on=[
                    TaskDependency(task_id="T-002", type=DependencyType.VALIDATES),
                ],
            ),
            Task(
                id="T-002",
                title="B",
                depends_on=[
                    TaskDependency(task_id="T-001", type=DependencyType.VALIDATES),
                ],
            ),
        ]
        result = validate_dag(tasks)
        assert result.valid is True


class TestDagMixedTypes:
    def test_mixed_blocking_and_nonblocking(self) -> None:
        """Only blocking deps affect execution order; non-blocking are ignored."""
        tasks = [
            Task(id="T-001", title="Feature"),
            Task(
                id="T-002",
                title="Test",
                depends_on=[
                    TaskDependency(task_id="T-001", type=DependencyType.VALIDATES),
                ],
            ),
            Task(
                id="T-003",
                title="Impl",
                depends_on=[
                    TaskDependency(task_id="T-001", type=DependencyType.BLOCKS),
                ],
            ),
        ]
        result = validate_dag(tasks)
        assert result.valid is True
        assert len(result.parallel_sets) == 2
        assert sorted(result.parallel_sets[0]) == ["T-001", "T-002"]
        assert result.parallel_sets[1] == ["T-003"]


class TestDagBackwardCompatStrings:
    def test_bare_strings_treated_as_blocks(self) -> None:
        """Legacy format: bare strings are blocking deps."""
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B", depends_on=["T-001"]),
        ]
        result = validate_dag(tasks)
        assert result.valid is True
        assert len(result.parallel_sets) == 2

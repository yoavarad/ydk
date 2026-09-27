"""Tests for task models — blocking-dependency semantics."""

import pytest

from ydk.models.pm import Dependency, DependencyType
from ydk.models.task import Task, TaskDependency, is_blocking_dependency


class TestIsBlockingDependency:
    def test_plain_string_is_blocking(self) -> None:
        assert is_blocking_dependency("#5") is True

    @pytest.mark.parametrize(
        "dep_type", [DependencyType.BLOCKS, DependencyType.CONDITIONAL_BLOCKS, DependencyType.WAITS_FOR]
    )
    def test_blocking_types(self, dep_type: DependencyType) -> None:
        assert is_blocking_dependency(Dependency(task_id="5", type=dep_type)) is True
        assert is_blocking_dependency(TaskDependency(task_id="5", type=dep_type)) is True

    @pytest.mark.parametrize("dep_type", [DependencyType.RELATED, DependencyType.VALIDATES, DependencyType.SUPERSEDES])
    def test_non_blocking_types(self, dep_type: DependencyType) -> None:
        assert is_blocking_dependency(Dependency(task_id="5", type=dep_type)) is False


class TestBlockingDepIds:
    def test_filters_non_blocking_and_strips_hash(self) -> None:
        task = Task(
            id="1",
            title="t",
            depends_on=["#2", TaskDependency(task_id="#3", type=DependencyType.RELATED), TaskDependency(task_id="4")],
        )
        assert task.blocking_dep_ids() == ["2", "4"]

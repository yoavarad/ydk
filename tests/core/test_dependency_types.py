"""Tests for rich dependency types — DependencyType enum, Dependency model, backward compat."""

import pytest
from pydantic import ValidationError

from ydk.models.pm import Dependency, DependencyType, TaskCreate, TaskDetail


class TestDependencyTypeEnum:
    def test_all_values(self) -> None:
        assert DependencyType.BLOCKS == "blocks"
        assert DependencyType.VALIDATES == "validates"
        assert DependencyType.CAUSED_BY == "caused-by"
        assert DependencyType.CONDITIONAL_BLOCKS == "conditional-blocks"
        assert DependencyType.WAITS_FOR == "waits-for"
        assert DependencyType.DISCOVERED_FROM == "discovered-from"
        assert DependencyType.SUPERSEDES == "supersedes"
        assert DependencyType.RELATED == "related"

    def test_is_str_enum(self) -> None:
        """DependencyType values are plain strings for YAML/JSON serialization."""
        for member in DependencyType:
            assert isinstance(member, str)
            assert member == member.value


class TestDependencyModel:
    def test_defaults_to_blocks(self) -> None:
        dep = Dependency(task_id="T-001")
        assert dep.type == DependencyType.BLOCKS

    def test_explicit_type(self) -> None:
        dep = Dependency(task_id="T-002", type=DependencyType.VALIDATES)
        assert dep.type == DependencyType.VALIDATES

    def test_string_type_coercion(self) -> None:
        dep = Dependency(task_id="T-003", type="validates")
        assert dep.type == DependencyType.VALIDATES

    def test_rejects_invalid_type(self) -> None:
        with pytest.raises(ValidationError):
            Dependency(task_id="T-001", type="invented-type")

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            Dependency(task_id="T-001", extra="bad")


class TestTaskCreateBackwardCompat:
    def test_bare_strings_still_accepted(self) -> None:
        """Existing code passing list[str] must continue to work."""
        t = TaskCreate(title="Test", dependencies=["T-001", "T-002"])
        assert t.dependencies == ["T-001", "T-002"]

    def test_typed_dependency_accepted(self) -> None:
        dep = Dependency(task_id="T-002", type=DependencyType.VALIDATES)
        t = TaskCreate(title="Test", dependencies=[dep])
        assert t.dependencies == [dep]

    def test_mixed_format(self) -> None:
        """Mix of bare strings and Dependency objects."""
        dep = Dependency(task_id="T-002", type="validates")
        t = TaskCreate(title="Test", dependencies=["T-001", dep])
        assert t.dependencies[0] == "T-001"
        assert isinstance(t.dependencies[1], Dependency)
        assert t.dependencies[1].type == DependencyType.VALIDATES

    def test_empty_dependencies_default(self) -> None:
        t = TaskCreate(title="Test")
        assert t.dependencies == []


class TestTaskDetailBackwardCompat:
    def test_bare_strings_still_accepted(self) -> None:
        td = TaskDetail(title="T", dependencies=["T-001"])
        assert td.dependencies == ["T-001"]

    def test_typed_dependency_accepted(self) -> None:
        dep = Dependency(task_id="T-001", type=DependencyType.WAITS_FOR)
        td = TaskDetail(title="T", dependencies=[dep])
        assert td.dependencies[0].type == DependencyType.WAITS_FOR

    def test_mixed_format(self) -> None:
        dep = Dependency(task_id="T-002", type="caused-by")
        td = TaskDetail(title="T", dependencies=["T-001", dep])
        assert td.dependencies[0] == "T-001"
        assert td.dependencies[1].type == DependencyType.CAUSED_BY

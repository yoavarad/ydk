"""Comprehensive tests for all task validation functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ydk.core.task_validator import (
    check_hierarchy,
    check_story_completeness,
    validate_batch_yaml,
    validate_component_ref,
    validate_dag,
    validate_spec_ref,
)
from ydk.models.pm import EpicSummary, StorySummary, TaskSummary
from ydk.models.task import Task

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Component ref validation
# ---------------------------------------------------------------------------


class TestValidateComponentRef:
    def test_valid_ref(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "entity" / "orders"
        comp_dir.mkdir(parents=True)
        (comp_dir / "Order.yaml").write_text("id: ydk:entity:orders/Order")

        err = validate_component_ref("ydk:entity:orders/Order", tmp_path)
        assert err is None

    def test_invalid_prefix(self, tmp_path: Path) -> None:
        err = validate_component_ref("bad:entity:orders/Order", tmp_path)
        assert err is not None
        assert "does not start with 'ydk:'" in err

    def test_missing_file(self, tmp_path: Path) -> None:
        err = validate_component_ref("ydk:entity:orders/Order", tmp_path)
        assert err is not None
        assert "not found at" in err

    def test_no_namespace(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "service"
        comp_dir.mkdir(parents=True)
        (comp_dir / "Auth.yaml").write_text("id: ydk:service:Auth")

        err = validate_component_ref("ydk:service:Auth", tmp_path)
        assert err is None

    def test_malformed_ref(self, tmp_path: Path) -> None:
        err = validate_component_ref("ydk:", tmp_path)
        assert err is not None
        assert "Invalid component ref format" in err


# ---------------------------------------------------------------------------
# Spec ref validation
# ---------------------------------------------------------------------------


class TestValidateSpecRef:
    def test_valid_ref(self, tmp_path: Path) -> None:
        spec = tmp_path / "docs" / "specs" / "01-core.md"
        spec.parent.mkdir(parents=True)
        spec.write_text("# Core spec")

        err = validate_spec_ref("docs/specs/01-core.md", tmp_path)
        assert err is None

    def test_missing_file(self, tmp_path: Path) -> None:
        err = validate_spec_ref("docs/specs/missing.md", tmp_path)
        assert err is not None
        assert "Spec file" in err
        assert "not found" in err


# ---------------------------------------------------------------------------
# Self-dependency detection
# ---------------------------------------------------------------------------


class TestSelfDependency:
    def test_self_loop_detected(self) -> None:
        tasks = [
            Task(id="T-001", title="A", depends_on=["T-001"]),
        ]
        result = validate_dag(tasks)
        assert result.valid is False
        assert result.cycles is not None
        assert "Self-dependency" in result.cycles[0]
        assert "T-001" in result.cycles[0]

    def test_no_self_loop(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B", depends_on=["T-001"]),
        ]
        result = validate_dag(tasks)
        assert result.valid is True


# ---------------------------------------------------------------------------
# Hierarchy check
# ---------------------------------------------------------------------------


class TestCheckHierarchy:
    def test_orphaned_task(self) -> None:
        tasks = [TaskSummary(id="T-001", title="Task")]
        # Attach story_id="" via object.__setattr__
        object.__setattr__(tasks[0], "story_id", "")
        stories: list[StorySummary] = []
        epics: list[EpicSummary] = []

        warnings = check_hierarchy(tasks, stories, epics)
        assert any("T-001" in w and "orphaned task" in w for w in warnings)

    def test_orphaned_story(self) -> None:
        tasks: list[TaskSummary] = []
        stories = [StorySummary(id="S-001", title="Story", epic_id="")]
        epics: list[EpicSummary] = []

        warnings = check_hierarchy(tasks, stories, epics)
        assert any("S-001" in w and "orphaned story" in w for w in warnings)

    def test_epic_with_no_stories(self) -> None:
        tasks: list[TaskSummary] = []
        stories: list[StorySummary] = []
        epics = [EpicSummary(id="E-001", title="Epic")]

        warnings = check_hierarchy(tasks, stories, epics)
        assert any("E-001" in w and "no stories" in w for w in warnings)

    def test_all_connected(self) -> None:
        tasks = [TaskSummary(id="T-001", title="Task")]
        object.__setattr__(tasks[0], "story_id", "S-001")
        stories = [StorySummary(id="S-001", title="Story", epic_id="E-001")]
        epics = [EpicSummary(id="E-001", title="Epic")]

        warnings = check_hierarchy(tasks, stories, epics)
        assert warnings == []


# ---------------------------------------------------------------------------
# Story completeness
# ---------------------------------------------------------------------------


class TestStoryCompleteness:
    def test_missing_spec_refs(self) -> None:
        stories = [StorySummary(id="S-001", title="Story")]

        detail = type("Detail", (), {"spec_refs": [], "acceptance_criteria": ["Some criterion"]})()
        warnings = check_story_completeness(stories, {"S-001": detail})
        assert any("S-001" in w and "no spec_refs" in w for w in warnings)

    def test_missing_acceptance(self) -> None:
        stories = [StorySummary(id="S-001", title="Story")]

        detail = type("Detail", (), {"spec_refs": ["docs/specs/01.md"], "acceptance_criteria": []})()
        warnings = check_story_completeness(stories, {"S-001": detail})
        assert any("S-001" in w and "no acceptance" in w for w in warnings)

    def test_complete_story_no_warnings(self) -> None:
        stories = [StorySummary(id="S-001", title="Story")]

        detail = type("Detail", (), {"spec_refs": ["docs/specs/01.md"], "acceptance_criteria": ["AC-1"]})()
        warnings = check_story_completeness(stories, {"S-001": detail})
        assert warnings == []

    def test_no_details_returns_empty(self) -> None:
        stories = [StorySummary(id="S-001", title="Story")]
        assert check_story_completeness(stories, None) == []


# ---------------------------------------------------------------------------
# Batch YAML validation
# ---------------------------------------------------------------------------


class TestValidateBatchYaml:
    def test_missing_title(self) -> None:
        data: dict[str, object] = {"tasks": [{"description": "no title"}]}
        errors = validate_batch_yaml(data)
        assert any("missing required field 'title'" in e for e in errors)

    def test_self_dependency(self) -> None:
        data: dict[str, object] = {
            "tasks": [
                {"id": "T-001", "title": "A", "depends_on": ["T-001"]},
            ]
        }
        errors = validate_batch_yaml(data)
        assert any("self-dependency" in e for e in errors)

    def test_missing_dep_in_yaml(self) -> None:
        data: dict[str, object] = {
            "tasks": [
                {"id": "T-001", "title": "A", "depends_on": ["T-999"]},
            ]
        }
        errors = validate_batch_yaml(data)
        assert any("T-999" in e and "not found" in e for e in errors)

    def test_invalid_dep_type(self) -> None:
        data: dict[str, object] = {
            "tasks": [
                {"id": "T-001", "title": "A"},
                {"id": "T-002", "title": "B", "depends_on": ["T-001:invalid-type"]},
            ]
        }
        errors = validate_batch_yaml(data)
        assert any("invalid dependency type" in e for e in errors)

    def test_valid_dep_type(self) -> None:
        data: dict[str, object] = {
            "tasks": [
                {"id": "T-001", "title": "A"},
                {"id": "T-002", "title": "B", "depends_on": ["T-001:validates"]},
            ]
        }
        errors = validate_batch_yaml(data)
        assert errors == []

    def test_story_ref_not_in_yaml(self) -> None:
        data: dict[str, object] = {
            "tasks": [
                {"id": "T-001", "title": "A", "story": "S-999"},
            ]
        }
        errors = validate_batch_yaml(data)
        assert any("S-999" in e and "not found" in e for e in errors)

    def test_epic_ref_not_in_yaml(self) -> None:
        data: dict[str, object] = {
            "stories": [
                {"id": "S-001", "title": "Story", "epic_id": "E-999"},
            ]
        }
        errors = validate_batch_yaml(data)
        assert any("E-999" in e and "not found" in e for e in errors)

    def test_component_refs_validated(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "components"
        comp_dir.mkdir()
        data: dict[str, object] = {
            "tasks": [
                {"id": "T-001", "title": "A", "component_refs": ["ydk:entity:orders/Order"]},
            ]
        }
        errors = validate_batch_yaml(data, components_dir=comp_dir)
        assert any("not found at" in e for e in errors)

    def test_spec_refs_validated(self, tmp_path: Path) -> None:
        data: dict[str, object] = {
            "tasks": [
                {"id": "T-001", "title": "A", "spec_refs": ["docs/specs/missing.md"]},
            ]
        }
        errors = validate_batch_yaml(data, specs_dir=tmp_path)
        assert any("not found" in e for e in errors)

    def test_fully_valid_batch(self) -> None:
        data: dict[str, object] = {
            "epics": [{"id": "E-001", "title": "Epic"}],
            "stories": [{"id": "S-001", "title": "Story", "epic_id": "E-001"}],
            "tasks": [
                {"id": "T-001", "title": "Task A", "story": "S-001"},
                {"id": "T-002", "title": "Task B", "story": "S-001", "depends_on": ["T-001:blocks"]},
            ],
        }
        errors = validate_batch_yaml(data)
        assert errors == []

    def test_non_mapping_entries(self) -> None:
        data: dict[str, object] = {
            "epics": ["not a mapping"],
            "stories": [42],
            "tasks": [None],
        }
        errors = validate_batch_yaml(data)
        assert len(errors) == 3
        assert all("not a mapping" in e for e in errors)

"""Comprehensive tests for all task validation functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ydk.core.task_validator import (
    check_hierarchy,
    check_story_completeness,
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

    def test_bare_name_resolves_via_spec_location(self, tmp_path: Path) -> None:
        spec = tmp_path / "docs" / "specs" / "orders.md"
        spec.parent.mkdir(parents=True)
        spec.write_text("# Orders", encoding="utf-8")

        assert validate_spec_ref("orders.md", tmp_path) is None

    def test_custom_spec_location(self, tmp_path: Path) -> None:
        spec = tmp_path / "specs" / "orders.md"
        spec.parent.mkdir(parents=True)
        spec.write_text("# Orders", encoding="utf-8")

        assert validate_spec_ref("orders.md", tmp_path) is not None
        assert validate_spec_ref("orders.md", tmp_path, spec_location="specs") is None

    def test_adr_path_resolves_from_root(self, tmp_path: Path) -> None:
        adr = tmp_path / "docs" / "adrs" / "0001-x.md"
        adr.parent.mkdir(parents=True)
        adr.write_text("# ADR", encoding="utf-8")

        assert validate_spec_ref("docs/adrs/0001-x.md", tmp_path) is None

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

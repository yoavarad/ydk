"""Tests for check_component_coverage in ydk.core.task_validator."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from ydk.core.task_validator import check_component_coverage

if TYPE_CHECKING:
    from pathlib import Path


class TestCheckComponentCoverage:
    def test_uncovered_components_reported(self, tmp_path: Path) -> None:
        """Components not referenced by any task are returned."""
        comp_dir = tmp_path / "components" / "entity"
        comp_dir.mkdir(parents=True)
        (comp_dir / "Order.yaml").write_text(yaml.dump({"id": "ydk:entity:orders/Order"}))
        (comp_dir / "User.yaml").write_text(yaml.dump({"id": "ydk:entity:users/User"}))

        # Only Order is referenced
        task_refs = {"T-001": ["ydk:entity:orders/Order"]}
        uncovered = check_component_coverage(tmp_path / "components", task_refs)
        assert uncovered == ["ydk:entity:users/User"]

    def test_all_covered(self, tmp_path: Path) -> None:
        """No components returned when all are referenced."""
        comp_dir = tmp_path / "components" / "entity"
        comp_dir.mkdir(parents=True)
        (comp_dir / "Order.yaml").write_text(yaml.dump({"id": "ydk:entity:orders/Order"}))

        task_refs = {"T-001": ["ydk:entity:orders/Order"]}
        uncovered = check_component_coverage(tmp_path / "components", task_refs)
        assert uncovered == []

    def test_empty_components_dir(self, tmp_path: Path) -> None:
        """Empty or nonexistent components dir returns empty list."""
        uncovered = check_component_coverage(tmp_path / "does-not-exist", {})
        assert uncovered == []

    def test_empty_yaml_files_skipped(self, tmp_path: Path) -> None:
        """YAML files without an id field are skipped."""
        comp_dir = tmp_path / "components"
        comp_dir.mkdir()
        (comp_dir / "empty.yaml").write_text("")
        (comp_dir / "no_id.yaml").write_text(yaml.dump({"name": "something"}))

        uncovered = check_component_coverage(comp_dir, {})
        assert uncovered == []

    def test_multiple_tasks_cover_same_component(self, tmp_path: Path) -> None:
        """A component referenced by multiple tasks is still covered."""
        comp_dir = tmp_path / "components" / "service"
        comp_dir.mkdir(parents=True)
        (comp_dir / "Auth.yaml").write_text(yaml.dump({"id": "ydk:service:Auth"}))

        task_refs = {
            "T-001": ["ydk:service:Auth"],
            "T-002": ["ydk:service:Auth"],
        }
        uncovered = check_component_coverage(tmp_path / "components", task_refs)
        assert uncovered == []

    def test_recursive_scan(self, tmp_path: Path) -> None:
        """Components in nested directories are found."""
        nested = tmp_path / "components" / "entity" / "billing" / "sub"
        nested.mkdir(parents=True)
        (nested / "Invoice.yaml").write_text(yaml.dump({"id": "ydk:entity:billing/sub/Invoice"}))

        uncovered = check_component_coverage(tmp_path / "components", {})
        assert uncovered == ["ydk:entity:billing/sub/Invoice"]

"""Tests for the test coverage checker."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path

from odk.core.test_coverage import TestCoverageChecker


def _write_component(components_dir: Path, comp_type: str, namespace: str, name: str) -> None:
    """Write a minimal component YAML file."""
    type_dir = components_dir / comp_type / namespace
    type_dir.mkdir(parents=True, exist_ok=True)
    cid = f"odk:{comp_type}:{namespace}/{name}"
    data = {"$schema": f"odk:schema:{comp_type}", "id": cid, "description": "test"}
    (type_dir / f"{name}.yaml").write_text(yaml.dump(data))


def _write_test_file(tests_dir: Path, filename: str) -> None:
    """Write a minimal test file."""
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / filename).write_text('"""Auto."""\n')


class TestCoverageCheckerFindsMatching:
    def test_entity_matched_by_name(self, tmp_path):
        components_dir = tmp_path / "components"
        tests_dir = tmp_path / "tests"
        _write_component(components_dir, "entity", "orders", "Order")
        _write_test_file(tests_dir, "test_order.py")

        checker = TestCoverageChecker()
        report = checker.check_coverage(components_dir, tests_dir)
        assert report.covered == 1
        assert report.uncovered == 0

    def test_entity_not_matched(self, tmp_path):
        components_dir = tmp_path / "components"
        tests_dir = tmp_path / "tests"
        _write_component(components_dir, "entity", "orders", "Order")
        _write_test_file(tests_dir, "test_user.py")

        checker = TestCoverageChecker()
        report = checker.check_coverage(components_dir, tests_dir)
        assert report.covered == 0
        assert report.uncovered == 1
        assert "odk:entity:orders/Order" in report.uncovered_ids

    def test_route_matched_by_all_segments(self, tmp_path):
        components_dir = tmp_path / "components"
        tests_dir = tmp_path / "tests"
        _write_component(components_dir, "route", "orders", "create")
        _write_test_file(tests_dir, "test_orders_create.py")

        checker = TestCoverageChecker()
        report = checker.check_coverage(components_dir, tests_dir)
        assert report.covered == 1

    def test_route_partial_match_fails(self, tmp_path):
        components_dir = tmp_path / "components"
        tests_dir = tmp_path / "tests"
        _write_component(components_dir, "route", "orders", "create")
        _write_test_file(tests_dir, "test_orders.py")  # missing 'create'

        checker = TestCoverageChecker()
        report = checker.check_coverage(components_dir, tests_dir)
        assert report.covered == 0

    def test_case_insensitive_match(self, tmp_path):
        components_dir = tmp_path / "components"
        tests_dir = tmp_path / "tests"
        _write_component(components_dir, "entity", "orders", "Order")
        _write_test_file(tests_dir, "test_ORDER_model.py")

        checker = TestCoverageChecker()
        report = checker.check_coverage(components_dir, tests_dir)
        assert report.covered == 1


class TestCoverageReportCalculation:
    def test_empty_components_dir(self, tmp_path):
        checker = TestCoverageChecker()
        report = checker.check_coverage(tmp_path / "nope", tmp_path / "tests")
        assert report.total_components == 0
        assert report.coverage_pct == 0.0
        assert report.by_type == []

    def test_percentage_calculation(self, tmp_path):
        components_dir = tmp_path / "components"
        tests_dir = tmp_path / "tests"
        _write_component(components_dir, "entity", "a", "Foo")
        _write_component(components_dir, "entity", "b", "Bar")
        _write_component(components_dir, "entity", "c", "Baz")
        _write_test_file(tests_dir, "test_foo.py")

        checker = TestCoverageChecker()
        report = checker.check_coverage(components_dir, tests_dir)
        assert report.total_components == 3
        assert report.covered == 1
        assert report.uncovered == 2
        assert report.coverage_pct == 33.3

    def test_by_type_breakdown(self, tmp_path):
        components_dir = tmp_path / "components"
        tests_dir = tmp_path / "tests"
        _write_component(components_dir, "entity", "a", "Foo")
        _write_component(components_dir, "route", "a", "bar")
        _write_test_file(tests_dir, "test_foo.py")

        checker = TestCoverageChecker()
        report = checker.check_coverage(components_dir, tests_dir)
        assert len(report.by_type) == 2
        entity_type = next(bt for bt in report.by_type if bt.type_name == "entity")
        route_type = next(bt for bt in report.by_type if bt.type_name == "route")
        assert entity_type.covered == 1
        assert route_type.covered == 0

    def test_nested_test_directory(self, tmp_path):
        components_dir = tmp_path / "components"
        tests_dir = tmp_path / "tests"
        _write_component(components_dir, "entity", "orders", "Order")
        nested = tests_dir / "integration"
        nested.mkdir(parents=True)
        (nested / "test_order_integration.py").write_text('"""test."""\n')

        checker = TestCoverageChecker()
        report = checker.check_coverage(components_dir, tests_dir)
        assert report.covered == 1

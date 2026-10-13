"""Tests for the test coverage checker."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path

from ydk.core.test_coverage import TestCoverageChecker


def _write_component(components_dir: Path, comp_type: str, namespace: str, name: str) -> None:
    """Write a minimal component YAML file."""
    type_dir = components_dir / comp_type / namespace
    type_dir.mkdir(parents=True, exist_ok=True)
    cid = f"ydk:{comp_type}:{namespace}/{name}"
    data = {"$schema": f"ydk:schema:{comp_type}", "id": cid, "description": "test"}
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
        assert "ydk:entity:orders/Order" in report.uncovered_ids

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


def _write_manifest(components_dir: Path, comp_type: str, cid: str, extra: dict) -> None:
    ns_name = cid.split(":", 2)[2]
    ns = ns_name.split("/")[0]
    type_dir = components_dir / comp_type / ns
    type_dir.mkdir(parents=True, exist_ok=True)
    data = {"id": cid, "description": "x", **extra}
    (type_dir / (ns_name.split("/")[1] + ".yaml")).write_text(yaml.dump(data))


def _manifest_project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path
    components = root / ".ydk" / "components"
    _write_manifest(
        components,
        "test",
        "ydk:test:messaging/store.unit",
        {
            "level": "unit",
            "target": "ydk:entity:messaging/Store",
            "cases": [
                {"name": "fifo-101", "req": "ydk:req:messaging/fifo"},
                {"name": "missing-1", "req": "ydk:req:messaging/fifo"},
            ],
        },
    )
    _write_manifest(
        components,
        "test",
        "ydk:test:messaging/send.e2e",
        {
            "level": "e2e",
            "target": "ydk:route:messaging/send",
            "cases": [{"name": "send-ok", "req": "ydk:req:messaging/send"}],
        },
    )
    _write_manifest(components, "req", "ydk:req:messaging/fifo", {})
    _write_manifest(components, "req", "ydk:req:messaging/send", {})
    _write_manifest(components, "req", "ydk:req:messaging/orphan", {})
    (root / "internal").mkdir()
    (root / "internal" / "store_test.go").write_text(
        'package x\nfunc TestStore(t *testing.T) {\n\tt.Run("fifo-101", func(t *testing.T) {})\n}\n'
        'func TestOther(t *testing.T) {\n\tt.Run("missing-1", func(t *testing.T) {})\n}\n'
    )
    (root / "test" / "e2e").mkdir(parents=True)
    (root / "test" / "e2e" / "send.sh").write_text("#!/bin/sh\n# ydk:test:messaging/send.e2e#send-ok\n")
    return components, root


class TestManifestCoverage:
    GLOBS = ("**/*_test.go", "test/e2e/**/*.sh")

    def test_go_t_run_marks_case_implemented(self, tmp_path):
        components, root = _manifest_project(tmp_path)
        report = TestCoverageChecker().check_coverage(
            components, root / "tests", test_globs=list(self.GLOBS), root=root
        )
        store = next(m for m in report.manifests if m.manifest_id == "ydk:test:messaging/store.unit")
        assert store.implemented == ["fifo-101"]
        assert store.missing == ["missing-1"]

    def test_shell_marker_marks_e2e_case_implemented(self, tmp_path):
        components, root = _manifest_project(tmp_path)
        report = TestCoverageChecker().check_coverage(
            components, root / "tests", test_globs=list(self.GLOBS), root=root
        )
        e2e = next(m for m in report.manifests if m.manifest_id == "ydk:test:messaging/send.e2e")
        assert e2e.implemented == ["send-ok"]
        assert e2e.missing == []

    def test_reqs_with_no_cases_listed(self, tmp_path):
        components, root = _manifest_project(tmp_path)
        report = TestCoverageChecker().check_coverage(
            components, root / "tests", test_globs=list(self.GLOBS), root=root
        )
        assert report.reqs_without_cases == ["ydk:req:messaging/orphan"]
        assert report.req_cases["ydk:req:messaging/fifo"] == [
            "ydk:test:messaging/store.unit#fifo-101",
            "ydk:test:messaging/store.unit#missing-1",
        ]

    def test_marker_prefix_not_confused(self, tmp_path):
        components, root = _manifest_project(tmp_path)
        (root / "test" / "e2e" / "send.sh").write_text("# ydk:test:messaging/send.e2e#send-ok-extra\n")
        report = TestCoverageChecker().check_coverage(
            components, root / "tests", test_globs=list(self.GLOBS), root=root
        )
        e2e = next(m for m in report.manifests if m.manifest_id == "ydk:test:messaging/send.e2e")
        assert e2e.missing == ["send-ok"]

"""Tests for the component checker — deterministic component quality validation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

import yaml

from ydk.core.component_checker import ComponentChecker
from ydk.models.evaluation import ComponentFinding


def _write_component(
    components_dir: Path,
    type_name: str,
    namespace: str,
    name: str,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write a component manifest YAML file and return its path."""
    component_id = f"ydk:{type_name}:{namespace}/{name}"
    rel_path = components_dir / type_name / namespace / f"{name}.yaml"
    rel_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "$schema": f"ydk:schema:{type_name}",
        "id": component_id,
        "description": f"Test {name}",
    }
    if extra:
        data.update(extra)
    rel_path.write_text(yaml.dump(data, default_flow_style=False))
    return rel_path


class TestRouteChecks:
    def test_route_without_error_responses(self, tmp_path: Path) -> None:
        components_dir = tmp_path / "components"
        schemas_dir = tmp_path / "schemas"
        _write_component(
            components_dir,
            "route",
            "orders",
            "create",
            extra={"responses": {"201": {"description": "Created"}}, "auth": "required"},
        )
        checker = ComponentChecker()
        findings = checker.check_all(components_dir, schemas_dir)
        route_findings = [f for f in findings if f.check == "route-missing-error-responses"]
        assert len(route_findings) == 1
        assert route_findings[0].severity == "error"
        assert "400" in route_findings[0].suggestion

    def test_route_with_error_responses_passes(self, tmp_path: Path) -> None:
        components_dir = tmp_path / "components"
        schemas_dir = tmp_path / "schemas"
        _write_component(
            components_dir,
            "route",
            "orders",
            "create",
            extra={
                "responses": {"201": {"description": "Created"}, "400": {"description": "Bad"}},
                "auth": "required",
            },
        )
        checker = ComponentChecker()
        findings = checker.check_all(components_dir, schemas_dir)
        route_findings = [f for f in findings if f.check == "route-missing-error-responses"]
        assert len(route_findings) == 0

    def test_route_missing_auth(self, tmp_path: Path) -> None:
        components_dir = tmp_path / "components"
        schemas_dir = tmp_path / "schemas"
        _write_component(
            components_dir,
            "route",
            "orders",
            "create",
            extra={"responses": {"201": {}, "400": {}}},
        )
        checker = ComponentChecker()
        findings = checker.check_all(components_dir, schemas_dir)
        auth_findings = [f for f in findings if f.check == "route-missing-auth"]
        assert len(auth_findings) == 1
        assert auth_findings[0].severity == "error"


class TestNfrChecks:
    def test_nfr_with_adjective_target(self, tmp_path: Path) -> None:
        components_dir = tmp_path / "components"
        schemas_dir = tmp_path / "schemas"
        _write_component(
            components_dir,
            "nfr",
            "perf",
            "latency",
            extra={"target": "fast", "unit": "ms"},
        )
        checker = ComponentChecker()
        findings = checker.check_all(components_dir, schemas_dir)
        nfr_findings = [f for f in findings if f.check == "nfr-non-numeric-target"]
        assert len(nfr_findings) == 1
        assert nfr_findings[0].severity == "error"
        assert "number" in nfr_findings[0].suggestion

    def test_nfr_missing_target(self, tmp_path: Path) -> None:
        components_dir = tmp_path / "components"
        schemas_dir = tmp_path / "schemas"
        _write_component(
            components_dir,
            "nfr",
            "perf",
            "latency",
            extra={"unit": "ms"},
        )
        checker = ComponentChecker()
        findings = checker.check_all(components_dir, schemas_dir)
        nfr_findings = [f for f in findings if f.check == "nfr-missing-target"]
        assert len(nfr_findings) == 1

    def test_nfr_missing_unit(self, tmp_path: Path) -> None:
        components_dir = tmp_path / "components"
        schemas_dir = tmp_path / "schemas"
        _write_component(
            components_dir,
            "nfr",
            "perf",
            "latency",
            extra={"target": 200},
        )
        checker = ComponentChecker()
        findings = checker.check_all(components_dir, schemas_dir)
        unit_findings = [f for f in findings if f.check == "nfr-missing-unit"]
        assert len(unit_findings) == 1
        assert unit_findings[0].severity == "warning"

    def test_nfr_valid_passes(self, tmp_path: Path) -> None:
        components_dir = tmp_path / "components"
        schemas_dir = tmp_path / "schemas"
        _write_component(
            components_dir,
            "nfr",
            "perf",
            "latency",
            extra={"target": 200, "unit": "ms"},
        )
        checker = ComponentChecker()
        findings = checker.check_all(components_dir, schemas_dir)
        nfr_findings = [f for f in findings if f.check.startswith("nfr-")]
        assert len(nfr_findings) == 0


class TestEntityChecks:
    def test_entity_states_without_transitions(self, tmp_path: Path) -> None:
        components_dir = tmp_path / "components"
        schemas_dir = tmp_path / "schemas"
        _write_component(
            components_dir,
            "entity",
            "orders",
            "Order",
            extra={"states": ["pending", "active", "cancelled"]},
        )
        checker = ComponentChecker()
        findings = checker.check_all(components_dir, schemas_dir)
        state_findings = [f for f in findings if f.check == "entity-states-without-transitions"]
        assert len(state_findings) == 1
        assert state_findings[0].severity == "error"

    def test_entity_unreachable_state(self, tmp_path: Path) -> None:
        components_dir = tmp_path / "components"
        schemas_dir = tmp_path / "schemas"
        _write_component(
            components_dir,
            "entity",
            "orders",
            "Order",
            extra={
                "states": ["pending", "active", "archived"],
                "transitions": [
                    {"from": "pending", "to": "active"},
                ],
            },
        )
        checker = ComponentChecker()
        findings = checker.check_all(components_dir, schemas_dir)
        unreachable = [f for f in findings if f.check == "entity-unreachable-state"]
        assert len(unreachable) == 1
        assert "archived" in unreachable[0].message

    def test_entity_all_states_reachable(self, tmp_path: Path) -> None:
        components_dir = tmp_path / "components"
        schemas_dir = tmp_path / "schemas"
        _write_component(
            components_dir,
            "entity",
            "orders",
            "Order",
            extra={
                "states": ["pending", "active"],
                "transitions": [
                    {"from": "pending", "to": "active"},
                ],
            },
        )
        checker = ComponentChecker()
        findings = checker.check_all(components_dir, schemas_dir)
        entity_findings = [f for f in findings if f.check.startswith("entity-")]
        assert len(entity_findings) == 0


class TestNamingChecks:
    def test_entity_not_pascal_case(self, tmp_path: Path) -> None:
        components_dir = tmp_path / "components"
        schemas_dir = tmp_path / "schemas"
        _write_component(components_dir, "entity", "orders", "orderModel")
        checker = ComponentChecker()
        findings = checker.check_all(components_dir, schemas_dir)
        naming_findings = [f for f in findings if f.check == "naming-not-pascal-case"]
        assert len(naming_findings) == 1
        assert "PascalCase" in naming_findings[0].suggestion

    def test_route_not_kebab_case(self, tmp_path: Path) -> None:
        components_dir = tmp_path / "components"
        schemas_dir = tmp_path / "schemas"
        _write_component(
            components_dir,
            "route",
            "orders",
            "CreateOrder",
            extra={"responses": {"400": {}}, "auth": "required"},
        )
        checker = ComponentChecker()
        findings = checker.check_all(components_dir, schemas_dir)
        naming_findings = [f for f in findings if f.check == "naming-not-kebab-case"]
        assert len(naming_findings) == 1
        assert "kebab-case" in naming_findings[0].suggestion

    def test_valid_names_pass(self, tmp_path: Path) -> None:
        components_dir = tmp_path / "components"
        schemas_dir = tmp_path / "schemas"
        _write_component(components_dir, "entity", "orders", "Order")
        _write_component(
            components_dir,
            "route",
            "orders",
            "create",
            extra={"responses": {"400": {}}, "auth": "required"},
        )
        checker = ComponentChecker()
        findings = checker.check_all(components_dir, schemas_dir)
        naming_findings = [f for f in findings if f.check.startswith("naming-")]
        assert len(naming_findings) == 0


class TestDescriptionChecks:
    def test_missing_description(self, tmp_path: Path) -> None:
        components_dir = tmp_path / "components"
        schemas_dir = tmp_path / "schemas"
        comp_dir = components_dir / "entity" / "orders"
        comp_dir.mkdir(parents=True)
        data = {"$schema": "ydk:schema:entity", "id": "ydk:entity:orders/Order", "description": ""}
        (comp_dir / "Order.yaml").write_text(yaml.dump(data))
        checker = ComponentChecker()
        findings = checker.check_all(components_dir, schemas_dir)
        desc_findings = [f for f in findings if f.check == "missing-description"]
        assert len(desc_findings) == 1
        assert desc_findings[0].severity == "warning"


class TestFindingModel:
    def test_finding_has_all_fields(self) -> None:
        finding = ComponentFinding(
            component_id="ydk:route:orders/create",
            file_path=".ydk/components/route/orders/create.yaml",
            check="route-missing-error-responses",
            severity="error",
            message="No error responses",
            suggestion="Add 400 and 401",
        )
        assert finding.component_id == "ydk:route:orders/create"
        assert finding.file_path == ".ydk/components/route/orders/create.yaml"
        assert finding.check == "route-missing-error-responses"
        assert finding.severity == "error"
        assert finding.message == "No error responses"
        assert finding.suggestion == "Add 400 and 401"

    def test_finding_forbids_extra_fields(self) -> None:
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="extra_field"):
            ComponentFinding(
                component_id="ydk:route:orders/create",
                file_path="x",
                check="x",
                severity="error",
                message="x",
                suggestion="x",
                extra_field="bad",
            )


class TestCheckAllEmpty:
    def test_no_components_returns_empty(self, tmp_path: Path) -> None:
        checker = ComponentChecker()
        findings = checker.check_all(tmp_path / "nonexistent", tmp_path / "schemas")
        assert findings == []

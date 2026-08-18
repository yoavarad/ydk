"""Tests for the component registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path

from ydk.core.component_registry import ComponentRegistry, ComponentRegistryError


def _write_schema(schemas_dir: Path, name: str, fields: dict | None = None) -> Path:
    schemas_dir.mkdir(parents=True, exist_ok=True)
    schema = {
        "name": name,
        "description": f"Schema for {name}",
        "version": 1,
        "fields": fields
        or {
            "id": {"type": "string", "required": True, "pattern": f"^ydk:{name}:.+", "description": "Component ID"},
            "description": {"type": "text", "required": True, "description": "What this is"},
        },
    }
    path = schemas_dir / f"{name}.yaml"
    path.write_text(yaml.dump(schema, default_flow_style=False))
    return path


def _write_component(
    components_dir: Path, type_name: str, namespace: str, name: str, extra: dict | None = None
) -> Path:
    component_id = f"ydk:{type_name}:{namespace}/{name}"
    rel_path = components_dir / type_name / namespace / f"{name}.yaml"
    rel_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "$schema": f"ydk:schema:{type_name}",
        "id": component_id,
        "description": f"Test {name}",
    }
    if extra:
        data.update(extra)
    rel_path.write_text(yaml.dump(data, default_flow_style=False))
    return rel_path


class TestLoadSchemas:
    def test_loads_yaml_schemas(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        _write_schema(schemas_dir, "route")
        _write_schema(schemas_dir, "entity")

        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=tmp_path / "components")
        schemas = reg.load_schemas()

        assert "route" in schemas
        assert "entity" in schemas
        assert schemas["route"].name == "route"

    def test_empty_schemas_dir(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=tmp_path / "components")
        assert reg.load_schemas() == {}

    def test_missing_schemas_dir(self, tmp_path):
        reg = ComponentRegistry(schemas_dir=tmp_path / "nonexistent", components_dir=tmp_path / "components")
        assert reg.load_schemas() == {}

    def test_caches_schemas(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        _write_schema(schemas_dir, "route")
        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=tmp_path / "components")

        result1 = reg.load_schemas()
        result2 = reg.load_schemas()
        assert result1 is result2


class TestResolveId:
    def test_resolves_standard_id(self, tmp_path):
        reg = ComponentRegistry(schemas_dir=tmp_path, components_dir=tmp_path / "components")
        path = reg.resolve_id("ydk:route:orders/create")
        assert path == tmp_path / "components" / "route" / "orders" / "create.yaml"

    def test_resolves_entity_id(self, tmp_path):
        reg = ComponentRegistry(schemas_dir=tmp_path, components_dir=tmp_path / "components")
        path = reg.resolve_id("ydk:entity:orders/Order")
        assert path == tmp_path / "components" / "entity" / "orders" / "Order.yaml"

    def test_resolves_crosscut_no_namespace(self, tmp_path):
        reg = ComponentRegistry(schemas_dir=tmp_path, components_dir=tmp_path / "components")
        path = reg.resolve_id("ydk:crosscut:error-format")
        assert path == tmp_path / "components" / "crosscut" / "error-format.yaml"

    def test_resolves_deep_namespace(self, tmp_path):
        reg = ComponentRegistry(schemas_dir=tmp_path, components_dir=tmp_path / "components")
        path = reg.resolve_id("ydk:nfr:perf/order-latency-p95")
        assert path == tmp_path / "components" / "nfr" / "perf" / "order-latency-p95.yaml"


class TestLoadComponent:
    def test_loads_valid_component(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        components_dir = tmp_path / "components"
        _write_schema(schemas_dir, "route")
        _write_component(components_dir, "route", "orders", "create")

        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=components_dir)
        manifest = reg.load_component("ydk:route:orders/create")
        assert manifest.id == "ydk:route:orders/create"
        assert manifest.schema_ref == "ydk:schema:route"

    def test_raises_for_missing_file(self, tmp_path):
        reg = ComponentRegistry(schemas_dir=tmp_path, components_dir=tmp_path / "components")
        with pytest.raises(ComponentRegistryError, match="not found"):
            reg.load_component("ydk:route:orders/nonexistent")


class TestValidateComponent:
    def test_valid_component_no_errors(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        components_dir = tmp_path / "components"
        _write_schema(
            schemas_dir,
            "route",
            fields={
                "id": {"type": "string", "required": True, "pattern": "^ydk:route:.+", "description": "ID"},
                "description": {"type": "text", "required": True, "description": "What this does"},
                "method": {"type": "enum", "required": True, "values": ["GET", "POST"], "description": "HTTP method"},
            },
        )
        _write_component(components_dir, "route", "orders", "create", extra={"method": "POST"})

        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=components_dir)
        errors = reg.validate_component("ydk:route:orders/create")
        assert errors == []

    def test_missing_required_field(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        components_dir = tmp_path / "components"
        _write_schema(
            schemas_dir,
            "route",
            fields={
                "id": {"type": "string", "required": True, "description": "ID"},
                "description": {"type": "text", "required": True, "description": "Desc"},
                "method": {"type": "enum", "required": True, "values": ["GET", "POST"], "description": "Method"},
            },
        )
        _write_component(components_dir, "route", "orders", "create")

        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=components_dir)
        errors = reg.validate_component("ydk:route:orders/create")
        assert any("method" in e for e in errors)

    def test_invalid_enum_value(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        components_dir = tmp_path / "components"
        _write_schema(
            schemas_dir,
            "route",
            fields={
                "id": {"type": "string", "required": True, "description": "ID"},
                "description": {"type": "text", "required": True, "description": "Desc"},
                "method": {"type": "enum", "required": True, "values": ["GET", "POST"], "description": "Method"},
            },
        )
        _write_component(components_dir, "route", "orders", "create", extra={"method": "INVALID"})

        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=components_dir)
        errors = reg.validate_component("ydk:route:orders/create")
        assert any("expected one of" in e for e in errors)

    def test_unknown_schema_type(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        components_dir = tmp_path / "components"
        schemas_dir.mkdir(parents=True, exist_ok=True)

        comp_path = components_dir / "widget" / "foo" / "bar.yaml"
        comp_path.parent.mkdir(parents=True, exist_ok=True)
        comp_path.write_text(
            yaml.dump(
                {
                    "$schema": "ydk:schema:widget",
                    "id": "ydk:widget:foo/bar",
                }
            )
        )

        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=components_dir)
        errors = reg.validate_component("ydk:widget:foo/bar")
        assert any("Unknown schema type" in e for e in errors)


class TestValidateAll:
    def test_validates_multiple_components(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        components_dir = tmp_path / "components"
        _write_schema(schemas_dir, "entity")
        _write_component(components_dir, "entity", "orders", "Order")
        _write_component(components_dir, "entity", "users", "User")

        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=components_dir)
        results = reg.validate_all()
        assert results == {}

    def test_empty_components_dir(self, tmp_path):
        reg = ComponentRegistry(schemas_dir=tmp_path, components_dir=tmp_path / "nonexistent")
        assert reg.validate_all() == {}


class TestListComponents:
    def test_lists_all(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        components_dir = tmp_path / "components"
        _write_schema(schemas_dir, "entity")
        _write_schema(schemas_dir, "route")
        _write_component(components_dir, "entity", "orders", "Order")
        _write_component(components_dir, "route", "orders", "create")

        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=components_dir)
        components = reg.list_components()
        ids = [c.full_id for c in components]
        assert "ydk:entity:orders/Order" in ids
        assert "ydk:route:orders/create" in ids

    def test_filter_by_type(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        components_dir = tmp_path / "components"
        _write_schema(schemas_dir, "entity")
        _write_schema(schemas_dir, "route")
        _write_component(components_dir, "entity", "orders", "Order")
        _write_component(components_dir, "route", "orders", "create")

        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=components_dir)
        components = reg.list_components(type_filter="entity")
        assert len(components) == 1
        assert components[0].type == "entity"


class TestListSchemas:
    def test_lists_available_schemas(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        _write_schema(schemas_dir, "route")
        _write_schema(schemas_dir, "entity")

        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=tmp_path / "components")
        schemas = reg.list_schemas()
        names = [s.name for s in schemas]
        assert "entity" in names
        assert "route" in names


class TestCreateComponent:
    def test_creates_from_template(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        components_dir = tmp_path / "components"
        _write_schema(schemas_dir, "route")

        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=components_dir)
        path = reg.create_component("route", "orders/cancel")

        assert path.exists()
        data = yaml.safe_load(path.read_text())
        assert data["$schema"] == "ydk:schema:route"
        assert data["id"] == "ydk:route:orders/cancel"

    def test_raises_for_unknown_type(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=tmp_path / "components")
        with pytest.raises(ComponentRegistryError, match="Unknown schema type"):
            reg.create_component("unknown", "foo/bar")

    def test_raises_for_existing_component(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        components_dir = tmp_path / "components"
        _write_schema(schemas_dir, "route")
        _write_component(components_dir, "route", "orders", "create")

        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=components_dir)
        with pytest.raises(ComponentRegistryError, match="already exists"):
            reg.create_component("route", "orders/create")

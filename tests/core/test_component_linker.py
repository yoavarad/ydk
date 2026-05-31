"""Tests for the component linker (Layer A)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path

from odk.core.component_linker import ComponentLinker
from odk.core.component_registry import ComponentRegistry


def _write_schema(schemas_dir: Path, name: str) -> None:
    schemas_dir.mkdir(parents=True, exist_ok=True)
    schema = {
        "name": name,
        "description": f"Schema for {name}",
        "version": 1,
        "fields": {
            "id": {"type": "string", "required": True, "description": "ID"},
            "description": {"type": "text", "required": True, "description": "Desc"},
        },
    }
    (schemas_dir / f"{name}.yaml").write_text(yaml.dump(schema, default_flow_style=False))


def _write_component(components_dir: Path, type_name: str, namespace: str, name: str, extra_content: str = "") -> Path:
    component_id = f"odk:{type_name}:{namespace}/{name}"
    rel_path = components_dir / type_name / namespace / f"{name}.yaml"
    rel_path.parent.mkdir(parents=True, exist_ok=True)
    content = f"$schema: odk:schema:{type_name}\nid: {component_id}\ndescription: Test {name}\n"
    if extra_content:
        content += extra_content
    rel_path.write_text(content)
    return rel_path


def _write_narrative(narratives_dir: Path, name: str, content: str) -> Path:
    narratives_dir.mkdir(parents=True, exist_ok=True)
    path = narratives_dir / name
    path.write_text(content)
    return path


class TestScanNarratives:
    def test_finds_references_in_markdown(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        components_dir = tmp_path / "components"
        narratives_dir = tmp_path / "specs"
        _write_schema(schemas_dir, "entity")

        _write_narrative(
            narratives_dir,
            "orders.md",
            "The [odk:entity:orders/Order] is created via [odk:route:orders/create].",
        )

        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=components_dir)
        linker = ComponentLinker(registry=reg, narratives_dir=narratives_dir)
        results = linker.scan_narratives()

        assert len(results) == 1
        path, refs = results[0]
        assert path.name == "orders.md"
        assert "odk:entity:orders/Order" in refs
        assert "odk:route:orders/create" in refs

    def test_no_refs_returns_empty(self, tmp_path):
        narratives_dir = tmp_path / "specs"
        _write_narrative(narratives_dir, "readme.md", "No component references here.")

        reg = ComponentRegistry(schemas_dir=tmp_path / "schemas", components_dir=tmp_path / "components")
        linker = ComponentLinker(registry=reg, narratives_dir=narratives_dir)
        results = linker.scan_narratives()
        assert results == []

    def test_missing_narratives_dir(self, tmp_path):
        reg = ComponentRegistry(schemas_dir=tmp_path / "schemas", components_dir=tmp_path / "components")
        linker = ComponentLinker(registry=reg, narratives_dir=tmp_path / "nonexistent")
        assert linker.scan_narratives() == []


class TestValidateReferences:
    def test_all_refs_valid(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        components_dir = tmp_path / "components"
        narratives_dir = tmp_path / "specs"

        _write_schema(schemas_dir, "entity")
        _write_schema(schemas_dir, "route")
        _write_component(components_dir, "entity", "orders", "Order")
        _write_component(components_dir, "route", "orders", "create")
        _write_narrative(
            narratives_dir,
            "orders.md",
            "See [odk:entity:orders/Order] and [odk:route:orders/create].",
        )

        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=components_dir)
        linker = ComponentLinker(registry=reg, narratives_dir=narratives_dir)
        result = linker.validate_references()

        assert result.undefined_refs == []
        assert result.broken_cross_refs == []
        assert len(result.valid_refs) == 2

    def test_detects_undefined_refs(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        components_dir = tmp_path / "components"
        narratives_dir = tmp_path / "specs"

        _write_schema(schemas_dir, "entity")
        _write_narrative(narratives_dir, "orders.md", "See [odk:entity:missing/Thing].")

        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=components_dir)
        linker = ComponentLinker(registry=reg, narratives_dir=narratives_dir)
        result = linker.validate_references()

        assert "odk:entity:missing/Thing" in result.undefined_refs

    def test_detects_orphaned_components(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        components_dir = tmp_path / "components"
        narratives_dir = tmp_path / "specs"

        _write_schema(schemas_dir, "entity")
        _write_component(components_dir, "entity", "orders", "Order")
        narratives_dir.mkdir(parents=True, exist_ok=True)

        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=components_dir)
        linker = ComponentLinker(registry=reg, narratives_dir=narratives_dir)
        result = linker.validate_references()

        assert "odk:entity:orders/Order" in result.orphaned_components


class TestValidateCrossRefs:
    def test_valid_cross_refs(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        components_dir = tmp_path / "components"

        _write_schema(schemas_dir, "route")
        _write_schema(schemas_dir, "entity")
        _write_component(components_dir, "entity", "orders", "Order")
        _write_component(
            components_dir,
            "route",
            "orders",
            "create",
            extra_content="response_ref: odk:entity:orders/Order\n",
        )

        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=components_dir)
        linker = ComponentLinker(registry=reg, narratives_dir=tmp_path / "specs")
        broken = linker.validate_cross_refs()
        assert broken == []

    def test_broken_cross_refs(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        components_dir = tmp_path / "components"

        _write_schema(schemas_dir, "route")
        _write_component(
            components_dir,
            "route",
            "orders",
            "create",
            extra_content="response_ref: odk:entity:missing/Thing\n",
        )

        reg = ComponentRegistry(schemas_dir=schemas_dir, components_dir=components_dir)
        linker = ComponentLinker(registry=reg, narratives_dir=tmp_path / "specs")
        broken = linker.validate_cross_refs()
        assert len(broken) == 1
        assert "odk:entity:missing/Thing" in broken[0]

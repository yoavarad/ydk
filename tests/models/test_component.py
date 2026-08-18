"""Tests for component manifest models."""

from __future__ import annotations

import pytest

from ydk.models.component import (
    ComponentId,
    ComponentManifest,
    LinkerResult,
    ScannerFinding,
    ScannerResult,
    SchemaDefinition,
    SchemaField,
    ValidationResult,
)


class TestComponentId:
    def test_parse_standard_id(self):
        cid = ComponentId.parse("ydk:route:orders/create")
        assert cid.full_id == "ydk:route:orders/create"
        assert cid.type == "route"
        assert cid.namespace == "orders"
        assert cid.name == "create"

    def test_parse_entity_pascal_case(self):
        cid = ComponentId.parse("ydk:entity:orders/Order")
        assert cid.type == "entity"
        assert cid.namespace == "orders"
        assert cid.name == "Order"

    def test_parse_deep_namespace(self):
        cid = ComponentId.parse("ydk:nfr:perf/order-latency-p95")
        assert cid.type == "nfr"
        assert cid.namespace == "perf"
        assert cid.name == "order-latency-p95"

    def test_parse_no_slash_single_name(self):
        cid = ComponentId.parse("ydk:crosscut:error-format")
        assert cid.type == "crosscut"
        assert cid.namespace == ""
        assert cid.name == "error-format"

    def test_parse_dotted_name(self):
        cid = ComponentId.parse("ydk:test:orders/placement.unit")
        assert cid.type == "test"
        assert cid.namespace == "orders"
        assert cid.name == "placement.unit"

    def test_invalid_missing_prefix(self):
        with pytest.raises(ValueError, match="must start with 'ydk:'"):
            ComponentId.parse("route:orders/create")

    def test_invalid_empty_type(self):
        with pytest.raises(ValueError, match="Invalid component ID format"):
            ComponentId.parse("ydk::orders/create")

    def test_invalid_no_colon_after_type(self):
        with pytest.raises(ValueError, match="Invalid component ID format"):
            ComponentId.parse("ydk:route")


class TestSchemaField:
    def test_minimal_field(self):
        f = SchemaField(type="string", description="A string field")
        assert f.type == "string"
        assert f.required is False
        assert f.pattern is None

    def test_enum_field(self):
        f = SchemaField(type="enum", description="Method", values=["GET", "POST"])
        assert f.values == ["GET", "POST"]

    def test_ref_field(self):
        f = SchemaField(type="ref", description="Target", ref_type="entity")
        assert f.ref_type == "entity"


class TestSchemaDefinition:
    def test_basic_schema(self):
        sd = SchemaDefinition(
            name="route",
            description="An API route",
            version=1,
            fields={
                "id": SchemaField(type="string", required=True, description="Component ID"),
                "method": SchemaField(type="enum", required=True, description="HTTP method", values=["GET", "POST"]),
            },
        )
        assert sd.name == "route"
        assert len(sd.fields) == 2
        assert sd.fields["method"].values == ["GET", "POST"]


class TestComponentManifest:
    def test_valid_manifest(self):
        m = ComponentManifest(schema_ref="ydk:schema:route", id="ydk:route:orders/create", method="POST")
        assert m.schema_ref == "ydk:schema:route"
        assert m.id == "ydk:route:orders/create"

    def test_invalid_schema_ref(self):
        with pytest.raises(ValueError, match="must start with 'ydk:schema:'"):
            ComponentManifest(schema_ref="bad:schema", id="ydk:route:orders/create")

    def test_invalid_id(self):
        with pytest.raises(ValueError, match="must start with 'ydk:'"):
            ComponentManifest(schema_ref="ydk:schema:route", id="route:orders/create")


class TestLinkerResult:
    def test_empty_result(self):
        r = LinkerResult(undefined_refs=[], orphaned_components=[], broken_cross_refs=[], valid_refs=[])
        assert r.undefined_refs == []
        assert r.orphaned_components == []

    def test_with_errors(self):
        r = LinkerResult(
            undefined_refs=["ydk:entity:missing/Thing"],
            orphaned_components=["ydk:error:unused/err"],
            broken_cross_refs=["ydk:route:a/b -> ydk:entity:c/d"],
            valid_refs=["ydk:entity:orders/Order"],
        )
        assert len(r.undefined_refs) == 1
        assert len(r.orphaned_components) == 1


class TestScannerResult:
    def test_empty_result(self):
        r = ScannerResult(unlinked_mentions=[], suggested_ids=[])
        assert r.unlinked_mentions == []

    def test_with_findings(self):
        finding = ScannerFinding(
            text="the Order model",
            line=42,
            suggested_id="ydk:entity:orders/Order",
            confidence="HIGH",
            reason="Mentions Order by name",
        )
        r = ScannerResult(unlinked_mentions=[finding], suggested_ids=["ydk:entity:orders/Order"])
        assert len(r.unlinked_mentions) == 1
        assert r.suggested_ids[0] == "ydk:entity:orders/Order"


class TestValidationResult:
    def test_combined_result(self):
        vr = ValidationResult(
            schema_errors={"ydk:route:a/b": ["missing field"]},
            linker_result=LinkerResult(undefined_refs=[], orphaned_components=[], broken_cross_refs=[], valid_refs=[]),
            scanner_result=None,
        )
        assert len(vr.schema_errors) == 1
        assert vr.scanner_result is None

"""Tests for catalog data models."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from odk.models.catalog import (
    CatalogItem,
    CatalogManifest,
    InputSpec,
    PublishCheck,
    Reference,
)


class TestInputSpec:
    """InputSpec model validation."""

    def test_required_fields(self) -> None:
        spec = InputSpec(schema_ref="odk-core-schemas/entity", version=">=1.0.0")
        assert spec.schema_ref == "odk-core-schemas/entity"
        assert spec.version == ">=1.0.0"
        assert spec.required is True

    def test_optional_required_false(self) -> None:
        spec = InputSpec(schema_ref="odk-core-schemas/route", version=">=2.0.0", required=False)
        assert spec.required is False

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            InputSpec(schema_ref="x", version="1", bogus="nope")  # type: ignore[call-arg]


class TestReference:
    """Reference model validation."""

    def test_basic(self) -> None:
        ref = Reference(name="python-quality", version=">=0.1.0")
        assert ref.name == "python-quality"
        assert ref.version == ">=0.1.0"

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Reference(name="x", version="1", extra="no")  # type: ignore[call-arg]


class TestPublishCheck:
    """PublishCheck model validation."""

    def test_defaults(self) -> None:
        check = PublishCheck(name="yaml-valid")
        assert check.description == ""
        assert check.command == ""

    def test_with_command(self) -> None:
        check = PublishCheck(name="lint", description="Run linter", command="ruff check .")
        assert check.command == "ruff check ."


class TestCatalogItem:
    """CatalogItem model validation."""

    def test_minimal(self) -> None:
        item = CatalogItem(name="test-item", version="1.0.0", path=Path("/tmp/test"))
        assert item.name == "test-item"
        assert item.tags == []
        assert item.path == Path("/tmp/test")

    def test_with_tags(self) -> None:
        item = CatalogItem(name="x", version="1", tags=["verification", "python"], path=Path("/tmp"))
        assert item.tags == ["verification", "python"]


class TestCatalogManifest:
    """CatalogManifest model validation."""

    def test_minimal(self) -> None:
        m = CatalogManifest(name="test", version="0.1.0")
        assert m.name == "test"
        assert m.tags == []
        assert m.inputs == {}
        assert m.verification_sets == []
        assert m.spec_reviewers == []
        assert m.component_schemas == []
        assert m.publish_checks == []

    def test_full_manifest(self) -> None:
        m = CatalogManifest(
            name="my-pack",
            version="1.0.0",
            description="A test pack",
            tags=["ignition-pack", "python"],
            inputs={"entities": InputSpec(schema_ref="odk-core-schemas/entity", version=">=1.0.0")},
            verification_sets=[Reference(name="python-quality", version=">=0.1.0")],
            spec_reviewers=[Reference(name="odk-default-reviewers", version=">=0.1.0")],
            component_schemas=[Reference(name="odk-core-schemas", version=">=0.1.0")],
            publish_checks=[PublishCheck(name="lint", command="ruff check .")],
        )
        assert len(m.inputs) == 1
        assert m.inputs["entities"].schema_ref == "odk-core-schemas/entity"
        assert len(m.verification_sets) == 1
        assert len(m.publish_checks) == 1

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CatalogManifest(name="x", version="1", unknown_field="bad")  # type: ignore[call-arg]

    def test_roundtrip_dict(self) -> None:
        m = CatalogManifest(
            name="test",
            version="1.0.0",
            tags=["verification"],
            publish_checks=[PublishCheck(name="check1")],
        )
        d = m.model_dump()
        m2 = CatalogManifest(**d)
        assert m == m2

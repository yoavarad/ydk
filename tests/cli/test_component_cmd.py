"""Tests for component CLI commands."""

from __future__ import annotations

from typer.testing import CliRunner

from odk.cli import app
from odk.core.component_registry import ComponentRegistryError
from odk.models.component import ComponentId, LinkerResult, SchemaDefinition, SchemaField

runner = CliRunner()


def _make_schema(name: str) -> SchemaDefinition:
    return SchemaDefinition(
        name=name,
        description=f"Schema for {name}",
        version=1,
        fields={
            "id": SchemaField(type="string", required=True, description="Component ID"),
            "description": SchemaField(type="text", required=True, description="What this is"),
        },
    )


class TestComponentList:
    def test_lists_components(self, monkeypatch):
        components = [
            ComponentId(full_id="odk:entity:orders/Order", type="entity", namespace="orders", name="Order"),
            ComponentId(full_id="odk:route:orders/create", type="route", namespace="orders", name="create"),
        ]
        monkeypatch.setattr(
            "odk.cli.component_cmd.ComponentRegistry.list_components",
            lambda self, type_filter=None: components,
        )
        result = runner.invoke(app, ["component", "list"])
        assert result.exit_code == 0
        assert "odk:entity:orders/Order" in result.output
        assert "odk:route:orders/create" in result.output

    def test_lists_with_type_filter(self, monkeypatch):
        components = [
            ComponentId(full_id="odk:entity:orders/Order", type="entity", namespace="orders", name="Order"),
        ]
        monkeypatch.setattr(
            "odk.cli.component_cmd.ComponentRegistry.list_components",
            lambda self, type_filter=None: components if type_filter == "entity" else [],
        )
        result = runner.invoke(app, ["component", "list", "--type", "entity"])
        assert result.exit_code == 0
        assert "odk:entity:orders/Order" in result.output

    def test_lists_empty(self, monkeypatch):
        monkeypatch.setattr(
            "odk.cli.component_cmd.ComponentRegistry.list_components",
            lambda self, type_filter=None: [],
        )
        result = runner.invoke(app, ["component", "list"])
        assert result.exit_code == 0
        assert "No components found" in result.output


class TestComponentShow:
    def test_shows_component(self, monkeypatch, tmp_path):
        from odk.models.component import ComponentManifest

        manifest = ComponentManifest(
            schema_ref="odk:schema:route",
            id="odk:route:orders/create",
            method="POST",
        )
        monkeypatch.setattr(
            "odk.cli.component_cmd.ComponentRegistry.load_component",
            lambda self, cid: manifest,
        )
        comp_file = tmp_path / "route" / "orders" / "create.yaml"
        comp_file.parent.mkdir(parents=True, exist_ok=True)
        comp_file.write_text("$schema: odk:schema:route\nid: odk:route:orders/create\nmethod: POST\n")
        monkeypatch.setattr(
            "odk.cli.component_cmd.ComponentRegistry.resolve_id",
            lambda self, cid: comp_file,
        )

        result = runner.invoke(app, ["component", "show", "odk:route:orders/create"])
        assert result.exit_code == 0
        assert "odk:route:orders/create" in result.output

    def test_shows_error_for_missing(self, monkeypatch):
        monkeypatch.setattr(
            "odk.cli.component_cmd.ComponentRegistry.load_component",
            lambda self, cid: (_ for _ in ()).throw(ComponentRegistryError("not found")),
        )
        result = runner.invoke(app, ["component", "show", "odk:route:missing/thing"])
        assert result.exit_code == 1


class TestComponentCreate:
    def test_creates_component(self, monkeypatch, tmp_path):
        created_path = tmp_path / "route" / "orders" / "cancel.yaml"
        monkeypatch.setattr(
            "odk.cli.component_cmd.ComponentRegistry.create_component",
            lambda self, t, n: created_path,
        )
        result = runner.invoke(app, ["component", "create", "route", "orders/cancel"])
        assert result.exit_code == 0
        assert "Created component" in result.output

    def test_create_fails_for_unknown_type(self, monkeypatch):
        monkeypatch.setattr(
            "odk.cli.component_cmd.ComponentRegistry.create_component",
            lambda self, t, n: (_ for _ in ()).throw(ComponentRegistryError("Unknown schema type")),
        )
        result = runner.invoke(app, ["component", "create", "unknown", "foo/bar"])
        assert result.exit_code == 1


class TestComponentValidate:
    def test_validate_all_pass(self, monkeypatch):
        from odk.core import component_linker

        monkeypatch.setattr(
            "odk.cli.component_cmd.ComponentRegistry.validate_all",
            lambda self: {},
        )
        monkeypatch.setattr(
            "odk.cli.component_cmd.ComponentRegistry.list_components",
            lambda self, type_filter=None: [
                ComponentId(full_id="odk:entity:orders/Order", type="entity", namespace="orders", name="Order"),
            ],
        )
        monkeypatch.setattr(
            component_linker.ComponentLinker,
            "validate_references",
            lambda self: LinkerResult(
                undefined_refs=[], orphaned_components=[], broken_cross_refs=[], valid_refs=["odk:entity:orders/Order"]
            ),
        )
        result = runner.invoke(app, ["component", "validate"])
        assert result.exit_code == 0
        assert "ALL PASSED" in result.output

    def test_validate_with_schema_errors(self, monkeypatch):
        from odk.core import component_linker

        monkeypatch.setattr(
            "odk.cli.component_cmd.ComponentRegistry.validate_all",
            lambda self: {"odk:route:a/b": ["missing required field 'method'"]},
        )
        monkeypatch.setattr(
            component_linker.ComponentLinker,
            "validate_references",
            lambda self: LinkerResult(undefined_refs=[], orphaned_components=[], broken_cross_refs=[], valid_refs=[]),
        )
        result = runner.invoke(app, ["component", "validate"])
        assert result.exit_code == 1
        assert "FAILED" in result.output


class TestComponentListSchemas:
    def test_lists_schemas(self, monkeypatch):
        schemas = [_make_schema("route"), _make_schema("entity")]
        monkeypatch.setattr(
            "odk.cli.component_cmd.ComponentRegistry.list_schemas",
            lambda self: schemas,
        )
        result = runner.invoke(app, ["component", "list-schemas"])
        assert result.exit_code == 0
        assert "route" in result.output
        assert "entity" in result.output

    def test_lists_empty_schemas(self, monkeypatch):
        monkeypatch.setattr(
            "odk.cli.component_cmd.ComponentRegistry.list_schemas",
            lambda self: [],
        )
        result = runner.invoke(app, ["component", "list-schemas"])
        assert result.exit_code == 0
        assert "No schemas found" in result.output


class TestComponentShowSchema:
    def test_shows_schema(self, monkeypatch):
        monkeypatch.setattr(
            "odk.cli.component_cmd.ComponentRegistry.load_schemas",
            lambda self: {"route": _make_schema("route")},
        )
        result = runner.invoke(app, ["component", "show-schema", "route"])
        assert result.exit_code == 0
        assert "route" in result.output

    def test_unknown_schema(self, monkeypatch):
        monkeypatch.setattr(
            "odk.cli.component_cmd.ComponentRegistry.load_schemas",
            lambda self: {},
        )
        result = runner.invoke(app, ["component", "show-schema", "unknown"])
        assert result.exit_code == 1


class TestComponentInitSchemas:
    def test_copies_default_schemas(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["component", "init-schemas"])
        assert result.exit_code == 0
        schemas_dir = tmp_path / ".odk" / "schemas"
        assert schemas_dir.is_dir()
        schema_files = list(schemas_dir.glob("*.yaml"))
        assert len(schema_files) == 14

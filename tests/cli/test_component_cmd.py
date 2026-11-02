"""Tests for component CLI commands."""

from __future__ import annotations

from typer.testing import CliRunner

from ydk.cli import app
from ydk.core.component_registry import ComponentRegistryError
from ydk.models.component import ComponentId, LinkerResult, SchemaDefinition, SchemaField

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
            ComponentId(full_id="ydk:entity:orders/Order", type="entity", namespace="orders", name="Order"),
            ComponentId(full_id="ydk:route:orders/create", type="route", namespace="orders", name="create"),
        ]
        monkeypatch.setattr(
            "ydk.cli.component_cmd.ComponentRegistry.list_components",
            lambda self, type_filter=None: components,
        )
        result = runner.invoke(app, ["component", "list"])
        assert result.exit_code == 0
        assert "ydk:entity:orders/Order" in result.output
        assert "ydk:route:orders/create" in result.output

    def test_lists_with_type_filter(self, monkeypatch):
        components = [
            ComponentId(full_id="ydk:entity:orders/Order", type="entity", namespace="orders", name="Order"),
        ]
        monkeypatch.setattr(
            "ydk.cli.component_cmd.ComponentRegistry.list_components",
            lambda self, type_filter=None: components if type_filter == "entity" else [],
        )
        result = runner.invoke(app, ["component", "list", "--type", "entity"])
        assert result.exit_code == 0
        assert "ydk:entity:orders/Order" in result.output

    def test_lists_empty(self, monkeypatch):
        monkeypatch.setattr(
            "ydk.cli.component_cmd.ComponentRegistry.list_components",
            lambda self, type_filter=None: [],
        )
        result = runner.invoke(app, ["component", "list"])
        assert result.exit_code == 0
        assert "No components found" in result.output


class TestComponentShow:
    def test_shows_component(self, monkeypatch, tmp_path):
        from ydk.models.component import ComponentManifest

        manifest = ComponentManifest(
            schema_ref="ydk:schema:route",
            id="ydk:route:orders/create",
            method="POST",
        )
        monkeypatch.setattr(
            "ydk.cli.component_cmd.ComponentRegistry.load_component",
            lambda self, cid: manifest,
        )
        comp_file = tmp_path / "route" / "orders" / "create.yaml"
        comp_file.parent.mkdir(parents=True, exist_ok=True)
        comp_file.write_text("$schema: ydk:schema:route\nid: ydk:route:orders/create\nmethod: POST\n")
        monkeypatch.setattr(
            "ydk.cli.component_cmd.ComponentRegistry.resolve_id",
            lambda self, cid: comp_file,
        )

        result = runner.invoke(app, ["component", "show", "ydk:route:orders/create"])
        assert result.exit_code == 0
        assert "ydk:route:orders/create" in result.output

    def test_shows_error_for_missing(self, monkeypatch):
        monkeypatch.setattr(
            "ydk.cli.component_cmd.ComponentRegistry.load_component",
            lambda self, cid: (_ for _ in ()).throw(ComponentRegistryError("not found")),
        )
        result = runner.invoke(app, ["component", "show", "ydk:route:missing/thing"])
        assert result.exit_code == 1


class TestComponentCreate:
    def test_creates_component(self, monkeypatch, tmp_path):
        created_path = tmp_path / "route" / "orders" / "cancel.yaml"
        monkeypatch.setattr(
            "ydk.cli.component_cmd.ComponentRegistry.create_component",
            lambda self, t, n: created_path,
        )
        result = runner.invoke(app, ["component", "create", "route", "orders/cancel"])
        assert result.exit_code == 0
        assert "Created component" in result.output

    def test_create_fails_for_unknown_type(self, monkeypatch):
        monkeypatch.setattr(
            "ydk.cli.component_cmd.ComponentRegistry.create_component",
            lambda self, t, n: (_ for _ in ()).throw(ComponentRegistryError("Unknown schema type")),
        )
        result = runner.invoke(app, ["component", "create", "unknown", "foo/bar"])
        assert result.exit_code == 1


class TestComponentValidate:
    def test_validate_all_pass(self, monkeypatch):
        from ydk.core import component_linker

        monkeypatch.setattr(
            "ydk.cli.component_cmd.ComponentRegistry.validate_all",
            lambda self: {},
        )
        monkeypatch.setattr(
            "ydk.cli.component_cmd.ComponentRegistry.list_components",
            lambda self, type_filter=None: [
                ComponentId(full_id="ydk:entity:orders/Order", type="entity", namespace="orders", name="Order"),
            ],
        )
        monkeypatch.setattr(
            component_linker.ComponentLinker,
            "validate_references",
            lambda self: LinkerResult(
                undefined_refs=[], orphaned_components=[], broken_cross_refs=[], valid_refs=["ydk:entity:orders/Order"]
            ),
        )
        result = runner.invoke(app, ["component", "validate"])
        assert result.exit_code == 0
        assert "ALL PASSED" in result.output

    def test_validate_with_schema_errors(self, monkeypatch):
        from ydk.core import component_linker

        monkeypatch.setattr(
            "ydk.cli.component_cmd.ComponentRegistry.validate_all",
            lambda self: {"ydk:route:a/b": ["missing required field 'method'"]},
        )
        monkeypatch.setattr(
            component_linker.ComponentLinker,
            "validate_references",
            lambda self: LinkerResult(undefined_refs=[], orphaned_components=[], broken_cross_refs=[], valid_refs=[]),
        )
        result = runner.invoke(app, ["component", "validate"])
        assert result.exit_code == 1
        assert "FAILED" in result.output

    def test_validate_uses_configured_spec_location(self, monkeypatch, tmp_path):
        from ydk.core import component_linker

        (tmp_path / ".ydk").mkdir()
        (tmp_path / ".ydk" / "config.yaml").write_text("project:\n  name: p\n  spec_location: custom/specs\n")
        monkeypatch.chdir(tmp_path)
        seen = {}
        orig_init = component_linker.ComponentLinker.__init__

        def spy(self, registry, narratives_dir):
            seen["dir"] = narratives_dir
            orig_init(self, registry, narratives_dir)

        monkeypatch.setattr(component_linker.ComponentLinker, "__init__", spy)
        runner.invoke(app, ["component", "validate"])
        assert str(seen["dir"]).replace("\\", "/") == "custom/specs"


class TestComponentListSchemas:
    def test_lists_schemas(self, monkeypatch):
        schemas = [_make_schema("route"), _make_schema("entity")]
        monkeypatch.setattr(
            "ydk.cli.component_cmd.ComponentRegistry.list_schemas",
            lambda self: schemas,
        )
        result = runner.invoke(app, ["component", "list-schemas"])
        assert result.exit_code == 0
        assert "route" in result.output
        assert "entity" in result.output

    def test_lists_empty_schemas(self, monkeypatch):
        monkeypatch.setattr(
            "ydk.cli.component_cmd.ComponentRegistry.list_schemas",
            lambda self: [],
        )
        result = runner.invoke(app, ["component", "list-schemas"])
        assert result.exit_code == 0
        assert "No schemas found" in result.output


class TestComponentShowSchema:
    def test_shows_schema(self, monkeypatch):
        monkeypatch.setattr(
            "ydk.cli.component_cmd.ComponentRegistry.load_schemas",
            lambda self: {"route": _make_schema("route")},
        )
        result = runner.invoke(app, ["component", "show-schema", "route"])
        assert result.exit_code == 0
        assert "route" in result.output

    def test_unknown_schema(self, monkeypatch):
        monkeypatch.setattr(
            "ydk.cli.component_cmd.ComponentRegistry.load_schemas",
            lambda self: {},
        )
        result = runner.invoke(app, ["component", "show-schema", "unknown"])
        assert result.exit_code == 1


class TestComponentInitSchemas:
    def test_copies_default_schemas(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["component", "init-schemas"])
        assert result.exit_code == 0
        schemas_dir = tmp_path / ".ydk" / "schemas"
        assert schemas_dir.is_dir()
        schema_files = list(schemas_dir.glob("*.yaml"))
        assert len(schema_files) == 14


class TestComponentInitSchemasUpgrade:
    def _stale(self, tmp_path):
        schemas_dir = tmp_path / ".ydk" / "schemas"
        schemas_dir.mkdir(parents=True)
        stale = schemas_dir / "contract.yaml"
        stale.write_text("name: contract\ndescription: old\nversion: 1\nfields: {}\n")
        return stale

    def test_default_skips_existing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        stale = self._stale(tmp_path)
        result = runner.invoke(app, ["component", "init-schemas"])
        assert result.exit_code == 0
        assert "description: old" in stale.read_text()

    def test_upgrade_replaces_stale(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        stale = self._stale(tmp_path)
        result = runner.invoke(app, ["component", "init-schemas", "--upgrade"])
        assert result.exit_code == 0
        assert "ext_ref" in stale.read_text()

    def test_force_replaces_stale(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        stale = self._stale(tmp_path)
        result = runner.invoke(app, ["component", "init-schemas", "--force"])
        assert result.exit_code == 0
        assert "ext_ref" in stale.read_text()

    def test_upgrade_leaves_identical_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["component", "init-schemas"])
        result = runner.invoke(app, ["component", "init-schemas", "--upgrade"])
        assert result.exit_code == 0
        assert "Upgraded" not in result.output


class TestComponentValidateWarnings:
    def test_prints_undeclared_field_warning(self, monkeypatch):
        from ydk.core import component_linker

        monkeypatch.setattr("ydk.cli.component_cmd.ComponentRegistry.validate_all", lambda self: {})
        monkeypatch.setattr(
            "ydk.cli.component_cmd.ComponentRegistry.warn_all",
            lambda self: {"ydk:contract:ns/A": ["Field 'ext_ref' is not declared"]},
        )
        monkeypatch.setattr(
            "ydk.cli.component_cmd.ComponentRegistry.list_components", lambda self, type_filter=None: []
        )
        monkeypatch.setattr(
            component_linker.ComponentLinker,
            "validate_references",
            lambda self: LinkerResult(undefined_refs=[], orphaned_components=[], broken_cross_refs=[], valid_refs=[]),
        )
        result = runner.invoke(app, ["component", "validate"])
        assert result.exit_code == 0
        assert "WARNING: ydk:contract:ns/A" in result.output
        assert "ext_ref" in result.output


class TestComponentScan:
    """`ydk component scan`: standalone Layer B scan via the subagent provider (system boundary)."""

    _SCHEMA = """name: entity
description: A domain object
version: 1
fields:
  id:
    type: string
    required: true
    description: id
"""
    _FINDING = {
        "text": "Order model",
        "line": 3,
        "suggested_id": "ydk:entity:orders/Order",
        "confidence": "HIGH",
        "reason": "mentioned without reference",
    }

    def _setup(self, tmp_path, monkeypatch, *, schemas: bool = True):
        monkeypatch.chdir(tmp_path)
        specs = tmp_path / "docs" / "specs"
        specs.mkdir(parents=True)
        (specs / "a.md").write_text("# A\n\nThe Order model.\n", encoding="utf-8")
        (specs / "sub").mkdir()
        (specs / "sub" / "b.md").write_text("# B\n\nOther.\n", encoding="utf-8")
        (tmp_path / ".ydk").mkdir()
        llm_dir = tmp_path / "llm"
        (tmp_path / ".ydk" / "config.yaml").write_text(
            f"project:\n  name: t\nai:\n  provider: subagent\n  subagent:\n    dir: {llm_dir.as_posix()}\n",
            encoding="utf-8",
        )
        if schemas:
            (tmp_path / ".ydk" / "schemas").mkdir()
            (tmp_path / ".ydk" / "schemas" / "entity.yaml").write_text(self._SCHEMA, encoding="utf-8")
        return llm_dir

    def _respond(self, llm_dir):
        import json

        (llm_dir / "responses").mkdir(exist_ok=True)
        for req in (llm_dir / "requests").glob("*.json"):
            (llm_dir / "responses" / req.name).write_text(json.dumps({"findings": [self._FINDING]}), encoding="utf-8")

    def test_handoff_exit_3_with_one_request_per_narrative(self, tmp_path, monkeypatch):
        import json

        llm_dir = self._setup(tmp_path, monkeypatch)
        result = runner.invoke(app, ["component", "scan"])
        assert result.exit_code == 3, result.output
        assert result.output.count("YDK-SUBAGENT-REQUESTS:") == 1
        requests = sorted((llm_dir / "requests").glob("*.json"))
        assert len(requests) == 2
        for req in requests:
            assert json.loads(req.read_text(encoding="utf-8"))["purpose"] == "layer-b-scan"

    def test_rerun_lists_findings_with_suggested_ids(self, tmp_path, monkeypatch):
        llm_dir = self._setup(tmp_path, monkeypatch)
        runner.invoke(app, ["component", "scan", "docs/specs/a.md"])
        self._respond(llm_dir)
        result = runner.invoke(app, ["component", "scan", "docs/specs/a.md"])
        assert result.exit_code == 0, result.output
        assert "ydk:entity:orders/Order" in result.output
        assert "a.md" in result.output

    def test_json_format_findings_carry_file(self, tmp_path, monkeypatch):
        import json

        llm_dir = self._setup(tmp_path, monkeypatch)
        runner.invoke(app, ["component", "scan", "docs/specs/a.md"])
        self._respond(llm_dir)
        result = runner.invoke(app, ["--format", "json", "component", "scan", "docs/specs/a.md"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["suggested_ids"] == ["ydk:entity:orders/Order"]
        assert data["unlinked_mentions"][0]["file"].endswith("a.md")

    def test_no_schemas_reports_nothing_to_scan(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch, schemas=False)
        result = runner.invoke(app, ["component", "scan"])
        assert result.exit_code == 0, result.output
        assert "No unlinked" in result.output

    def test_missing_path_exits_1(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        result = runner.invoke(app, ["component", "scan", "nope"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

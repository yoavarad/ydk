"""Tests for the ydk test CLI commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from typer.testing import CliRunner

import ydk.cli  # noqa: F401
from ydk.cli.main import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _setup_project(tmp_path: Path, comp_type: str = "entity") -> None:
    """Set up a minimal .ydk project structure."""
    schemas_dir = tmp_path / ".ydk" / "schemas"
    schemas_dir.mkdir(parents=True)
    components_dir = tmp_path / ".ydk" / "components" / comp_type / "orders"
    components_dir.mkdir(parents=True)

    # Write schema
    schema = {
        "name": comp_type,
        "description": f"Test {comp_type}",
        "version": 1,
        "fields": {
            "id": {"type": "string", "required": True, "description": "ID"},
            "name": {"type": "string", "required": True, "description": "Name"},
        },
    }
    (schemas_dir / f"{comp_type}.yaml").write_text(yaml.dump(schema))

    # Write component
    if comp_type == "entity":
        component = {
            "$schema": f"ydk:schema:{comp_type}",
            "id": f"ydk:{comp_type}:orders/Order",
            "name": "Order",
        }
    elif comp_type == "route":
        component = {
            "$schema": f"ydk:schema:{comp_type}",
            "id": f"ydk:{comp_type}:orders/create",
            "method": "POST",
            "path": "/orders",
            "status": 201,
        }
    else:
        component = {
            "$schema": f"ydk:schema:{comp_type}",
            "id": f"ydk:{comp_type}:orders/NotFound",
        }
    (components_dir / "Order.yaml").write_text(yaml.dump(component))


class TestGenerateCommand:
    def test_generate_entity_to_stdout(self, tmp_path, monkeypatch):
        _setup_project(tmp_path, "entity")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["test", "generate", "--from", "ydk:entity:orders/Order"])
        assert result.exit_code == 0
        assert "test_" in result.output.lower() or "def test_" in result.output

    def test_generate_entity_to_file(self, tmp_path, monkeypatch):
        _setup_project(tmp_path, "entity")
        monkeypatch.chdir(tmp_path)
        out_file = tmp_path / "output" / "test_order.py"

        result = runner.invoke(
            app, ["test", "generate", "--from", "ydk:entity:orders/Order", "--output", str(out_file)]
        )
        assert result.exit_code == 0
        assert out_file.exists()
        assert "def test_" in out_file.read_text()

    def test_generate_unknown_component_fails(self, tmp_path, monkeypatch):
        _setup_project(tmp_path, "entity")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["test", "generate", "--from", "ydk:entity:nope/Nope"])
        assert result.exit_code == 1


class TestCoverageCommand:
    def test_coverage_no_components(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["test", "coverage"])
        assert result.exit_code == 0
        assert "No components" in result.output

    def test_coverage_with_components(self, tmp_path, monkeypatch):
        _setup_project(tmp_path, "entity")
        # Create a matching test file
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_order.py").write_text('"""test."""\n')
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["test", "coverage"])
        assert result.exit_code == 0
        assert "entity" in result.output.lower() or "Coverage" in result.output


def _setup_test_manifest(tmp_path: Path, level: str = "unit") -> None:
    d = tmp_path / ".ydk" / "components" / "test" / "messaging"
    d.mkdir(parents=True)
    (tmp_path / ".ydk" / "schemas").mkdir(parents=True)
    data = {
        "$schema": "ydk:schema:test",
        "id": f"ydk:test:messaging/store.{level}",
        "description": "x",
        "level": level,
        "target": "ydk:entity:messaging/Store",
        "cases": [
            {"name": "fifo-101", "description": "d", "given": "g", "when": "w", "then": "t"},
            {"name": "empty-pop", "description": "d", "given": "g", "when": "w", "then": "t"},
        ],
    }
    (d / f"store.{level}.yaml").write_text(yaml.dump(data))


class TestGenerateGoFromTestManifest:
    def test_no_output_prints_stdout_and_writes_nothing(self, tmp_path, monkeypatch):
        _setup_test_manifest(tmp_path)
        monkeypatch.chdir(tmp_path)
        before = {p.name for p in tmp_path.iterdir()}
        result = runner.invoke(app, ["test", "generate", "--from", "ydk:test:messaging/store.unit", "--lang", "go"])
        assert result.exit_code == 0, result.output
        assert result.output.count("t.Run(") == 2
        assert {p.name for p in tmp_path.iterdir()} == before

    def test_output_flag_writes_file(self, tmp_path, monkeypatch):
        _setup_test_manifest(tmp_path)
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "messaging" / "store_test.go"
        result = runner.invoke(
            app, ["test", "generate", "--from", "ydk:test:messaging/store.unit", "--lang", "go", "-o", str(out)]
        )
        assert result.exit_code == 0, result.output
        assert out.read_text().count("t.Run(") == 2

    def test_integration_build_tag(self, tmp_path, monkeypatch):
        _setup_test_manifest(tmp_path, "integration")
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app, ["test", "generate", "--from", "ydk:test:messaging/store.integration", "--lang", "go"]
        )
        assert result.exit_code == 0, result.output
        assert result.output.startswith("//go:build integration")

    def test_existing_file_not_overwritten_missing_reported(self, tmp_path, monkeypatch):
        _setup_test_manifest(tmp_path)
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "messaging" / "store_test.go"
        target.parent.mkdir()
        original = (
            'package messaging\n\nfunc TestStore(t *testing.T) {\n\tt.Run("fifo-101", func(t *testing.T) {})\n}\n'
        )
        target.write_text(original)
        result = runner.invoke(
            app,
            ["test", "generate", "--from", "ydk:test:messaging/store.unit", "--lang", "go", "-o", str(target)],
        )
        assert result.exit_code == 0, result.output
        assert target.read_text() == original
        assert "empty-pop" in result.output
        assert "fifo-101" not in result.output

    def test_non_go_lang_for_test_manifest_errors(self, tmp_path, monkeypatch):
        _setup_test_manifest(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["test", "generate", "--from", "ydk:test:messaging/store.unit"])
        assert result.exit_code == 1

"""Validates the python-fastapi-hexagonal ignition pack has all required files."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
import yaml

PACK_ROOT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "catalog" / "python-fastapi-hexagonal"


class TestPackMetadata:
    """Pack must have catalog.yaml, manifest.yaml, and publish-checks.yaml."""

    def test_catalog_yaml_exists(self) -> None:
        assert (PACK_ROOT / "catalog.yaml").is_file()

    def test_catalog_yaml_valid(self) -> None:
        data = yaml.safe_load((PACK_ROOT / "catalog.yaml").read_text())
        assert data["name"] == "python-fastapi-hexagonal"
        assert data["version"] == "1.0.0"
        assert "inputs" in data
        assert "entity" in data["inputs"]
        assert "route" in data["inputs"]
        assert "contract" in data["inputs"]

    def test_manifest_yaml_exists(self) -> None:
        assert (PACK_ROOT / "manifest.yaml").is_file()

    def test_manifest_yaml_has_generators(self) -> None:
        data = yaml.safe_load((PACK_ROOT / "manifest.yaml").read_text())
        assert "generators" in data
        assert len(data["generators"]) >= 15

    def test_manifest_generator_scripts_exist(self) -> None:
        data = yaml.safe_load((PACK_ROOT / "manifest.yaml").read_text())
        for gen in data["generators"]:
            script_path = PACK_ROOT / gen["script"]
            assert script_path.is_file(), f"Generator script missing: {gen['script']}"

    def test_publish_checks_yaml_exists(self) -> None:
        assert (PACK_ROOT / "publish-checks.yaml").is_file()

    def test_readme_exists(self) -> None:
        assert (PACK_ROOT / "README.md").is_file()

    def test_changelog_exists(self) -> None:
        assert (PACK_ROOT / "CHANGELOG.md").is_file()


class TestGenerators:
    """All required generator files must be present."""

    REQUIRED_GENERATORS: ClassVar[list[str]] = [
        "sqlalchemy_models.py",
        "repository_ports.py",
        "protocol_ports.py",
        "db_postgres_repos.py",
        "pydantic_schemas.py",
        "fastapi_service_stubs.py",
        "fastapi_routes.py",
        "fastapi_dependencies.py",
        "app_factory.py",
        "alembic_initial.py",
        "fake_repos.py",
        "fake_ports.py",
        "conftest_generator.py",
        "unit_test_stubs.py",
        "route_test_stubs.py",
        "schema_tests.py",
        "contract_tests.py",
        "integration_conftest.py",
        "e2e_conftest.py",
        "unit_test_bodies.py",
        "integration_test_bodies.py",
        "e2e_test_bodies.py",
        "openapi_spec_export.py",
        "adapter_stubs.py",
        "contracts_snapshot.py",
    ]

    @pytest.mark.parametrize("filename", REQUIRED_GENERATORS)
    def test_generator_exists(self, filename: str) -> None:
        assert (PACK_ROOT / "generators" / filename).is_file(), f"Missing generator: {filename}"


class TestContextModules:
    """Shared _context utilities must be present."""

    REQUIRED_CONTEXT: ClassVar[list[str]] = ["__init__.py", "naming.py", "types.py", "imports.py", "todos.py"]

    @pytest.mark.parametrize("filename", REQUIRED_CONTEXT)
    def test_context_module_exists(self, filename: str) -> None:
        assert (PACK_ROOT / "generators" / "_context" / filename).is_file(), f"Missing context module: {filename}"


class TestTemplates:
    """All Jinja2 template directories must have at least one .j2 file."""

    REQUIRED_TEMPLATE_DIRS: ClassVar[list[str]] = [
        "models",
        "schemas",
        "services",
        "routes",
        "ports",
        "repos",
        "di",
        "app",
        "migrations",
        "tests",
    ]

    @pytest.mark.parametrize("subdir", REQUIRED_TEMPLATE_DIRS)
    def test_template_dir_has_j2_files(self, subdir: str) -> None:
        tpl_dir = PACK_ROOT / "templates" / subdir
        assert tpl_dir.is_dir(), f"Missing template directory: {subdir}"
        j2_files = list(tpl_dir.glob("*.j2"))
        assert len(j2_files) >= 1, f"No .j2 files in templates/{subdir}/"


class TestSamples:
    """Sample components must exist for testing the pack."""

    REQUIRED_SAMPLES: ClassVar[list[str]] = [
        "components/entity/sample/Item.yaml",
        "components/route/sample/create.yaml",
        "components/contract/sample/ItemService.yaml",
        "components/error/sample/not-found.yaml",
    ]

    @pytest.mark.parametrize("sample_path", REQUIRED_SAMPLES)
    def test_sample_exists(self, sample_path: str) -> None:
        assert (PACK_ROOT / "samples" / sample_path).is_file(), f"Missing sample: {sample_path}"

    @pytest.mark.parametrize("sample_path", REQUIRED_SAMPLES)
    def test_sample_valid_yaml(self, sample_path: str) -> None:
        data = yaml.safe_load((PACK_ROOT / "samples" / sample_path).read_text())
        assert isinstance(data, dict)
        assert "name" in data or "tag" in data or "path" in data or "id" in data


class TestContextNaming:
    """Context naming module must have the expected interface."""

    def test_naming_has_expected_functions(self) -> None:
        naming_path = PACK_ROOT / "generators" / "_context" / "naming.py"
        content = naming_path.read_text()
        assert "def to_snake(" in content
        assert "def to_pascal(" in content
        assert "def iter_fields(" in content
        assert "def derive_name(" in content
        assert "def derive_table_name(" in content
        assert "def pk_type(" in content

"""Structural tests for the dotnet-webapi-clean ignition pack.

Verifies that all expected files are present and well-formed, mirroring
nextjs-fsd-shadcn's tests/test_pack_structure.py.
"""

from __future__ import annotations

from pathlib import Path

import yaml

PACK_ROOT = Path(__file__).parent.parent

EXPECTED_GENERATORS = [
    "solution_scaffold.py",
    "program_and_config.py",
    "domain_entities.py",
    "efcore_dbcontext.py",
    "repository_interfaces.py",
    "repository_implementations.py",
    "service_stubs.py",
    "api_endpoints.py",
    "dependency_injection.py",
    "fake_repositories.py",
    "unit_test_stubs.py",
    "endpoint_test_stubs.py",
    "entity_test_stubs.py",
]

EXPECTED_CONTEXT_MODULES = [
    "__init__.py",
    "naming.py",
    "types.py",
    "imports.py",
]

EXPECTED_TEMPLATES = [
    "api/appsettings.json.j2",
    "api/endpoints.cs.j2",
    "api/launchsettings.json.j2",
    "api/program.cs.j2",
    "api/service_collection_extensions.cs.j2",
    "application/repository_interface.cs.j2",
    "application/service_interface.cs.j2",
    "application/service_stub.cs.j2",
    "domain/entity.cs.j2",
    "infrastructure/dbcontext.cs.j2",
    "infrastructure/entity_configuration.cs.j2",
    "infrastructure/repository_impl.cs.j2",
    "solution/.editorconfig.j2",
    "solution/Directory.Build.props.j2",
    "solution/api.csproj.j2",
    "solution/application.csproj.j2",
    "solution/domain.csproj.j2",
    "solution/infrastructure.csproj.j2",
    "solution/tests.csproj.j2",
    "solution/webapiclean.sln.j2",
    "tests/endpoint_test.cs.j2",
    "tests/entity_test.cs.j2",
    "tests/fake_repository.cs.j2",
    "tests/service_test.cs.j2",
]

EXPECTED_TOP_LEVEL = [
    "catalog.yaml",
    "manifest.yaml",
    "publish-checks.yaml",
    "README.md",
    "CHANGELOG.md",
]

EXPECTED_SAMPLES = [
    "components/entity/sample/Widget.yaml",
    "components/contract/sample/WidgetService.yaml",
    "components/route/sample/create.yaml",
]


def test_top_level_files_exist() -> None:
    for name in EXPECTED_TOP_LEVEL:
        path = PACK_ROOT / name
        assert path.exists(), f"Missing top-level file: {name}"
        assert path.stat().st_size > 0, f"Empty top-level file: {name}"


def test_all_generators_present() -> None:
    generators_dir = PACK_ROOT / "generators"
    for name in EXPECTED_GENERATORS:
        path = generators_dir / name
        assert path.exists(), f"Missing generator: {name}"
        assert path.stat().st_size > 0, f"Empty generator: {name}"


def test_all_context_modules_present() -> None:
    context_dir = PACK_ROOT / "generators" / "_context"
    for name in EXPECTED_CONTEXT_MODULES:
        path = context_dir / name
        assert path.exists(), f"Missing _context module: {name}"


def test_all_templates_present() -> None:
    templates_dir = PACK_ROOT / "templates"
    for name in EXPECTED_TEMPLATES:
        path = templates_dir / name
        assert path.exists(), f"Missing template: {name}"
        assert path.stat().st_size > 0, f"Empty template: {name}"


def test_catalog_yaml_valid() -> None:
    catalog = yaml.safe_load((PACK_ROOT / "catalog.yaml").read_text())
    assert catalog["name"] == "dotnet-webapi-clean"
    assert catalog["version"] == "1.0.0"
    assert "ignition-pack" in catalog["tags"]
    assert "inputs" in catalog
    assert "entity" in catalog["inputs"]
    assert "route" in catalog["inputs"]
    assert "contract" in catalog["inputs"]


def test_manifest_yaml_valid() -> None:
    manifest = yaml.safe_load((PACK_ROOT / "manifest.yaml").read_text())
    assert "generators" in manifest
    generator_ids = [g["id"] for g in manifest["generators"]]
    assert "solution-scaffold" in generator_ids
    assert "program-and-config" in generator_ids
    assert "domain-entities" in generator_ids
    assert "efcore-dbcontext" in generator_ids
    assert "repository-interfaces" in generator_ids
    assert "repository-implementations" in generator_ids
    assert "service-stubs" in generator_ids
    assert "api-endpoints" in generator_ids
    assert "dependency-injection" in generator_ids
    assert "fake-repositories" in generator_ids
    assert "unit-test-stubs" in generator_ids
    assert "endpoint-test-stubs" in generator_ids
    assert "entity-test-stubs" in generator_ids


def test_manifest_generator_scripts_exist() -> None:
    manifest = yaml.safe_load((PACK_ROOT / "manifest.yaml").read_text())
    for gen in manifest["generators"]:
        script_path = PACK_ROOT / gen["script"]
        assert script_path.is_file(), f"Generator script missing: {gen['script']}"


def test_publish_checks_yaml_valid() -> None:
    checks = yaml.safe_load((PACK_ROOT / "publish-checks.yaml").read_text())
    assert "checks" in checks
    assert len(checks["checks"]) >= 1


def test_samples_present_and_valid() -> None:
    samples_dir = PACK_ROOT / "samples"
    for sample_path in EXPECTED_SAMPLES:
        path = samples_dir / sample_path
        assert path.is_file(), f"Missing sample: {sample_path}"
        data = yaml.safe_load(path.read_text())
        assert isinstance(data, dict)
        assert "id" in data


def test_samples_components_has_at_least_one_sample() -> None:
    samples_dir = PACK_ROOT / "samples" / "components"
    assert samples_dir.exists(), "samples/components/ directory must exist"
    yaml_files = list(samples_dir.glob("**/*.yaml"))
    assert len(yaml_files) >= 1, "At least one sample component must exist"

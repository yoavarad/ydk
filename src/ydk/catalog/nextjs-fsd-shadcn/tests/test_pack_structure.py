"""Structural tests for the nextjs-fsd-shadcn ignition pack.

Verifies that all expected files are present and well-formed.
"""

from __future__ import annotations

from pathlib import Path

import yaml

PACK_ROOT = Path(__file__).parent.parent

EXPECTED_GENERATORS = [
    "auth_provider.py",
    "derive_features.py",
    "msw_handlers.py",
    "navigation_config.py",
    "nextjs_api_client.py",
    "nextjs_features.py",
    "ydk_adapter.py",
    "openapi_sdk.py",
    "page_containers.py",
    "page_scaffolding.py",
    "page_shells.py",
    "query_hooks.py",
    "typescript_types.py",
    "widget_stubs.py",
]

EXPECTED_CONTEXT_MODULES = [
    "__init__.py",
    "naming.py",
    "types.py",
    "imports.py",
]

EXPECTED_TEMPLATES = [
    "entities/types.ts.j2",
    "features/query-hook.ts.j2",
    "shared/query-keys.ts.j2",
    "shared/navigation.ts.j2",
    "pages/page-hook.ts.j2",
    "pages/page-container.tsx.j2",
    "pages/page-shell.tsx.j2",
]

EXPECTED_TOP_LEVEL = [
    "catalog.yaml",
    "manifest.yaml",
    "publish-checks.yaml",
    "README.md",
    "CHANGELOG.md",
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
    assert catalog["name"] == "nextjs-fsd-shadcn"
    assert catalog["version"] == "1.0.0"
    assert "ignition-pack" in catalog["tags"]
    assert "inputs" in catalog
    assert "page" in catalog["inputs"]
    assert "route" in catalog["inputs"]


def test_manifest_yaml_valid() -> None:
    manifest = yaml.safe_load((PACK_ROOT / "manifest.yaml").read_text())
    assert manifest["name"] == "nextjs-fsd-shadcn"
    assert "generators" in manifest
    generator_ids = [g["id"] for g in manifest["generators"]]
    assert "derive-features" in generator_ids
    assert "typescript-types" in generator_ids
    assert "openapi-sdk" in generator_ids
    assert "nextjs-features" in generator_ids
    assert "page-scaffolding" in generator_ids
    assert "query-hooks" in generator_ids
    assert "page-shells" in generator_ids
    assert "page-containers" in generator_ids
    assert "widget-stubs" in generator_ids
    assert "navigation-config" in generator_ids
    assert "auth-provider" in generator_ids
    assert "msw-handlers" in generator_ids
    assert "nextjs-api-client" in generator_ids


def test_manifest_generator_order_is_sequential() -> None:
    manifest = yaml.safe_load((PACK_ROOT / "manifest.yaml").read_text())
    orders = [g["order"] for g in manifest["generators"]]
    assert orders == sorted(orders), "Generator order values must be sequential"
    assert len(set(orders)) == len(orders), "Generator order values must be unique"


def test_publish_checks_yaml_valid() -> None:
    checks = yaml.safe_load((PACK_ROOT / "publish-checks.yaml").read_text())
    assert "checks" in checks
    assert len(checks["checks"]) >= 1


def test_samples_directory_exists() -> None:
    samples_dir = PACK_ROOT / "samples" / "components"
    assert samples_dir.exists(), "samples/components/ directory must exist"
    tsx_files = list(samples_dir.glob("*.tsx"))
    assert len(tsx_files) >= 1, "At least one sample component must exist"

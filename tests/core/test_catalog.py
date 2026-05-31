"""Tests for LocalCatalogBackend — search, get, install, publish, uninstall."""

from pathlib import Path

import pytest
import yaml

from odk.core.catalog import LocalCatalogBackend, _load_manifest


def _create_catalog_item(base: Path, name: str, tags: list[str] | None = None, version: str = "0.1.0") -> Path:
    """Helper: create a minimal catalog item directory with catalog.yaml + README."""
    item_dir = base / name
    item_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "version": version,
        "description": f"Test item {name}",
        "tags": tags or [],
    }
    (item_dir / "catalog.yaml").write_text(yaml.dump(manifest))
    (item_dir / "README.md").write_text(f"# {name}\n\nTest catalog item.\n")
    return item_dir


class TestLoadManifest:
    """Test _load_manifest helper."""

    def test_valid_manifest(self, tmp_path: Path) -> None:
        item = _create_catalog_item(tmp_path, "test-item", tags=["verification"])
        manifest = _load_manifest(item)
        assert manifest is not None
        assert manifest.name == "test-item"
        assert manifest.tags == ["verification"]

    def test_missing_catalog_yaml(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        assert _load_manifest(empty_dir) is None

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        item_dir = tmp_path / "bad"
        item_dir.mkdir()
        (item_dir / "catalog.yaml").write_text("not: [valid: yaml: {{")
        # pyyaml may parse this oddly but it should not crash
        result = _load_manifest(item_dir)
        # Either None or a valid manifest depending on parsing
        assert result is None or result.name is not None


class TestLocalCatalogBackendSearch:
    """Test keyword search."""

    def test_search_by_name(self, tmp_path: Path) -> None:
        _create_catalog_item(tmp_path, "python-quality", tags=["verification", "python"])
        _create_catalog_item(tmp_path, "hexagonal-architecture", tags=["verification", "architecture"])
        backend = LocalCatalogBackend(catalog_dir=tmp_path, include_builtin=False)

        results = backend.search("python")
        assert len(results) == 1
        assert results[0].name == "python-quality"

    def test_search_by_tag_content(self, tmp_path: Path) -> None:
        _create_catalog_item(tmp_path, "my-verifier", tags=["verification", "python"])
        backend = LocalCatalogBackend(catalog_dir=tmp_path, include_builtin=False)

        results = backend.search("verification")
        assert len(results) == 1

    def test_search_with_tag_filter(self, tmp_path: Path) -> None:
        _create_catalog_item(tmp_path, "python-quality", tags=["verification", "python"])
        _create_catalog_item(tmp_path, "python-types", tags=["component-schemas", "python"])
        backend = LocalCatalogBackend(catalog_dir=tmp_path, include_builtin=False)

        results = backend.search("python", tags=["verification"])
        assert len(results) == 1
        assert results[0].name == "python-quality"

    def test_search_empty_catalog(self, tmp_path: Path) -> None:
        backend = LocalCatalogBackend(catalog_dir=tmp_path, include_builtin=False)
        results = backend.search("anything")
        assert results == []

    def test_search_no_match(self, tmp_path: Path) -> None:
        _create_catalog_item(tmp_path, "python-quality", tags=["verification"])
        backend = LocalCatalogBackend(catalog_dir=tmp_path, include_builtin=False)
        results = backend.search("terraform")
        assert results == []

    def test_search_nonexistent_dir(self, tmp_path: Path) -> None:
        backend = LocalCatalogBackend(catalog_dir=tmp_path / "nonexistent", include_builtin=False)
        results = backend.search("anything")
        assert results == []


class TestLocalCatalogBackendGet:
    """Test get by name."""

    def test_get_existing(self, tmp_path: Path) -> None:
        _create_catalog_item(tmp_path, "python-quality", tags=["verification"], version="1.2.3")
        backend = LocalCatalogBackend(catalog_dir=tmp_path, include_builtin=False)

        item = backend.get("python-quality")
        assert item is not None
        assert item.name == "python-quality"
        assert item.version == "1.2.3"

    def test_get_with_version(self, tmp_path: Path) -> None:
        _create_catalog_item(tmp_path, "test-item", version="2.0.0")
        backend = LocalCatalogBackend(catalog_dir=tmp_path, include_builtin=False)

        assert backend.get("test-item", version="2.0.0") is not None
        assert backend.get("test-item", version="1.0.0") is None

    def test_get_nonexistent(self, tmp_path: Path) -> None:
        backend = LocalCatalogBackend(catalog_dir=tmp_path, include_builtin=False)
        assert backend.get("nonexistent") is None


class TestLocalCatalogBackendInstall:
    """Test install copies to correct directories based on tags."""

    def test_install_verification(self, tmp_path: Path) -> None:
        catalog_dir = tmp_path / "catalog"
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        _create_catalog_item(catalog_dir, "python-quality", tags=["verification"])
        backend = LocalCatalogBackend(catalog_dir=catalog_dir, include_builtin=False)
        backend.install("python-quality", None, project_dir)

        dest = project_dir / ".odk" / "verifications" / "python-quality"
        assert dest.exists()
        assert (dest / "catalog.yaml").exists()

    def test_install_schemas(self, tmp_path: Path) -> None:
        catalog_dir = tmp_path / "catalog"
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        _create_catalog_item(catalog_dir, "odk-core-schemas", tags=["component-schemas"])
        backend = LocalCatalogBackend(catalog_dir=catalog_dir, include_builtin=False)
        backend.install("odk-core-schemas", None, project_dir)

        dest = project_dir / ".odk" / "schemas" / "odk-core-schemas"
        assert dest.exists()

    def test_install_spec_reviewers(self, tmp_path: Path) -> None:
        catalog_dir = tmp_path / "catalog"
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        _create_catalog_item(catalog_dir, "my-reviewers", tags=["spec-reviewers"])
        backend = LocalCatalogBackend(catalog_dir=catalog_dir, include_builtin=False)
        backend.install("my-reviewers", None, project_dir)

        dest = project_dir / ".odk" / "spec-reviewers" / "my-reviewers"
        assert dest.exists()

    def test_install_default_location(self, tmp_path: Path) -> None:
        catalog_dir = tmp_path / "catalog"
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        _create_catalog_item(catalog_dir, "misc-tool", tags=["utility"])
        backend = LocalCatalogBackend(catalog_dir=catalog_dir, include_builtin=False)
        backend.install("misc-tool", None, project_dir)

        dest = project_dir / ".odk" / "catalog-installed" / "misc-tool"
        assert dest.exists()

    def test_install_records_lock(self, tmp_path: Path) -> None:
        catalog_dir = tmp_path / "catalog"
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        _create_catalog_item(catalog_dir, "my-item", tags=["verification"], version="1.0.0")
        backend = LocalCatalogBackend(catalog_dir=catalog_dir, include_builtin=False)
        backend.install("my-item", None, project_dir)

        lock_path = project_dir / ".odk" / "catalog-lock.yaml"
        assert lock_path.exists()
        lock = yaml.safe_load(lock_path.read_text())
        assert len(lock["installed"]) == 1
        assert lock["installed"][0]["name"] == "my-item"

    def test_install_nonexistent_raises(self, tmp_path: Path) -> None:
        backend = LocalCatalogBackend(catalog_dir=tmp_path, include_builtin=False)
        with pytest.raises(ValueError, match="not found"):
            backend.install("nonexistent", None, tmp_path)

    def test_install_overwrites_existing(self, tmp_path: Path) -> None:
        catalog_dir = tmp_path / "catalog"
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        _create_catalog_item(catalog_dir, "my-item", tags=["verification"], version="1.0.0")
        backend = LocalCatalogBackend(catalog_dir=catalog_dir, include_builtin=False)
        backend.install("my-item", None, project_dir)
        # Install again should overwrite without error
        backend.install("my-item", None, project_dir)

        dest = project_dir / ".odk" / "verifications" / "my-item"
        assert dest.exists()


class TestLocalCatalogBackendListInstalled:
    """Test list_installed reads from lock file."""

    def test_empty_project(self, tmp_path: Path) -> None:
        backend = LocalCatalogBackend(catalog_dir=tmp_path, include_builtin=False)
        assert backend.list_installed(tmp_path) == []

    def test_with_installed_items(self, tmp_path: Path) -> None:
        catalog_dir = tmp_path / "catalog"
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        _create_catalog_item(catalog_dir, "item-a", tags=["verification"])
        _create_catalog_item(catalog_dir, "item-b", tags=["spec-reviewers"])
        backend = LocalCatalogBackend(catalog_dir=catalog_dir, include_builtin=False)
        backend.install("item-a", None, project_dir)
        backend.install("item-b", None, project_dir)

        installed = backend.list_installed(project_dir)
        names = [i.name for i in installed]
        assert "item-a" in names
        assert "item-b" in names


class TestLocalCatalogBackendPublish:
    """Test publish validates and copies to catalog."""

    def test_publish_valid_item(self, tmp_path: Path) -> None:
        catalog_dir = tmp_path / "catalog"
        source = tmp_path / "source" / "my-item"
        source.mkdir(parents=True)
        (source / "catalog.yaml").write_text(yaml.dump({"name": "my-item", "version": "1.0.0", "tags": []}))
        (source / "README.md").write_text("# My Item\n")

        backend = LocalCatalogBackend(catalog_dir=catalog_dir, include_builtin=False)
        backend.publish(source)

        assert (catalog_dir / "my-item" / "catalog.yaml").exists()
        assert (catalog_dir / "my-item" / "README.md").exists()

    def test_publish_missing_catalog_yaml(self, tmp_path: Path) -> None:
        source = tmp_path / "source" / "bad"
        source.mkdir(parents=True)
        (source / "README.md").write_text("# No manifest\n")

        backend = LocalCatalogBackend(catalog_dir=tmp_path / "catalog", include_builtin=False)
        with pytest.raises(ValueError, match=r"No valid catalog\.yaml"):
            backend.publish(source)

    def test_publish_missing_readme(self, tmp_path: Path) -> None:
        source = tmp_path / "source" / "no-readme"
        source.mkdir(parents=True)
        (source / "catalog.yaml").write_text(yaml.dump({"name": "no-readme", "version": "1.0.0", "tags": []}))

        backend = LocalCatalogBackend(catalog_dir=tmp_path / "catalog", include_builtin=False)
        with pytest.raises(ValueError, match=r"Missing required file: README\.md"):
            backend.publish(source)

    def test_publish_with_failing_check(self, tmp_path: Path) -> None:
        source = tmp_path / "source" / "failing"
        source.mkdir(parents=True)
        manifest = {
            "name": "failing",
            "version": "1.0.0",
            "tags": [],
            "publish_checks": [{"name": "always-fail", "command": "false"}],
        }
        (source / "catalog.yaml").write_text(yaml.dump(manifest))
        (source / "README.md").write_text("# Failing\n")

        backend = LocalCatalogBackend(catalog_dir=tmp_path / "catalog", include_builtin=False)
        with pytest.raises(ValueError, match="Publish check 'always-fail' failed"):
            backend.publish(source)


class TestCheckUninstalledDeps:
    """Test check_uninstalled_deps reports missing referenced deps."""

    def test_reports_uninstalled_refs(self, tmp_path: Path) -> None:
        catalog_dir = tmp_path / "catalog"
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create a pack that references verification_sets and spec_reviewers
        pack_dir = catalog_dir / "my-pack"
        pack_dir.mkdir(parents=True)
        manifest = {
            "name": "my-pack",
            "version": "1.0.0",
            "description": "Pack with deps",
            "tags": ["ignition-pack"],
            "verification_sets": [{"name": "python-quality", "version": ">=1.0.0"}],
            "spec_reviewers": [{"name": "arch-reviewer", "version": ">=1.0.0"}],
            "component_schemas": [{"name": "core-schemas", "version": ">=1.0.0"}],
        }
        (pack_dir / "catalog.yaml").write_text(yaml.dump(manifest))
        (pack_dir / "README.md").write_text("# my-pack\n")

        backend = LocalCatalogBackend(catalog_dir=catalog_dir, include_builtin=False)
        deps = backend.check_uninstalled_deps("my-pack", None, project_dir)
        assert "python-quality" in deps
        assert "arch-reviewer" in deps
        assert "core-schemas" in deps

    def test_already_installed_not_reported(self, tmp_path: Path) -> None:
        catalog_dir = tmp_path / "catalog"
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create the referenced item and install it
        _create_catalog_item(catalog_dir, "python-quality", tags=["verification"])
        backend = LocalCatalogBackend(catalog_dir=catalog_dir, include_builtin=False)
        backend.install("python-quality", None, project_dir)

        # Create a pack referencing python-quality
        pack_dir = catalog_dir / "my-pack"
        pack_dir.mkdir(parents=True)
        manifest = {
            "name": "my-pack",
            "version": "1.0.0",
            "description": "Pack with deps",
            "tags": ["ignition-pack"],
            "verification_sets": [{"name": "python-quality", "version": ">=1.0.0"}],
        }
        (pack_dir / "catalog.yaml").write_text(yaml.dump(manifest))
        (pack_dir / "README.md").write_text("# my-pack\n")

        deps = backend.check_uninstalled_deps("my-pack", None, project_dir)
        assert deps == []

    def test_no_refs_returns_empty(self, tmp_path: Path) -> None:
        catalog_dir = tmp_path / "catalog"
        _create_catalog_item(catalog_dir, "simple-item", tags=["verification"])
        backend = LocalCatalogBackend(catalog_dir=catalog_dir, include_builtin=False)
        deps = backend.check_uninstalled_deps("simple-item", None, tmp_path)
        assert deps == []

    def test_nonexistent_item_returns_empty(self, tmp_path: Path) -> None:
        backend = LocalCatalogBackend(catalog_dir=tmp_path, include_builtin=False)
        deps = backend.check_uninstalled_deps("ghost", None, tmp_path)
        assert deps == []


class TestLocalCatalogBackendUninstall:
    """Test uninstall removes items."""

    def test_uninstall_existing(self, tmp_path: Path) -> None:
        catalog_dir = tmp_path / "catalog"
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        _create_catalog_item(catalog_dir, "removable", tags=["verification"])
        backend = LocalCatalogBackend(catalog_dir=catalog_dir, include_builtin=False)
        backend.install("removable", None, project_dir)

        assert backend.uninstall("removable", project_dir) is True
        assert not (project_dir / ".odk" / "verifications" / "removable").exists()

        installed = backend.list_installed(project_dir)
        assert all(i.name != "removable" for i in installed)

    def test_uninstall_nonexistent(self, tmp_path: Path) -> None:
        backend = LocalCatalogBackend(catalog_dir=tmp_path, include_builtin=False)
        assert backend.uninstall("ghost", tmp_path) is False

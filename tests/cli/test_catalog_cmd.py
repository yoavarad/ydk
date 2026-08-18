"""Tests for the ydk catalog CLI commands."""

from pathlib import Path

import yaml
from typer.testing import CliRunner

import ydk.cli  # noqa: F401  # Register all commands
from ydk.cli.main import app
from ydk.core.catalog import LocalCatalogBackend

runner = CliRunner()


def _create_catalog_item(
    base: Path, name: str, tags: list[str] | None = None, version: str = "0.1.0", description: str = ""
) -> Path:
    """Helper: create a minimal catalog item directory."""
    item_dir = base / name
    item_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "version": version,
        "description": description or f"Test item {name}",
        "tags": tags or [],
    }
    (item_dir / "catalog.yaml").write_text(yaml.dump(manifest))
    (item_dir / "README.md").write_text(f"# {name}\n\nTest catalog item.\n")
    return item_dir


class TestCatalogSearch:
    """Test ydk catalog search."""

    def test_search_found(self, tmp_path: Path, monkeypatch: object) -> None:
        catalog_dir = tmp_path / "catalog"
        _create_catalog_item(catalog_dir, "python-quality", tags=["verification", "python"])

        import ydk.cli.catalog_cmd as cmd

        monkeypatch.setattr(cmd, "_default_catalog_dir", lambda: catalog_dir)  # type: ignore[attr-defined]

        result = runner.invoke(app, ["catalog", "search", "python"])
        assert result.exit_code == 0
        assert "python-quality" in result.output

    def test_search_no_results(self, tmp_path: Path, monkeypatch: object) -> None:
        catalog_dir = tmp_path / "catalog"
        catalog_dir.mkdir()

        import ydk.cli.catalog_cmd as cmd

        monkeypatch.setattr(cmd, "_default_catalog_dir", lambda: catalog_dir)  # type: ignore[attr-defined]

        result = runner.invoke(app, ["catalog", "search", "nothing"])
        assert result.exit_code == 0
        assert "No items found" in result.output

    def test_search_tag_filter(self, tmp_path: Path, monkeypatch: object) -> None:
        catalog_dir = tmp_path / "catalog"
        _create_catalog_item(catalog_dir, "python-quality", tags=["verification", "python"])
        _create_catalog_item(catalog_dir, "java-quality", tags=["verification", "java"])

        import ydk.cli.catalog_cmd as cmd

        monkeypatch.setattr(cmd, "_default_catalog_dir", lambda: catalog_dir)  # type: ignore[attr-defined]

        result = runner.invoke(app, ["catalog", "search", "quality", "--tag", "python"])
        assert result.exit_code == 0
        assert "python-quality" in result.output
        assert "java-quality" not in result.output

    def test_search_json_format(self, tmp_path: Path, monkeypatch: object) -> None:
        catalog_dir = tmp_path / "catalog"
        _create_catalog_item(catalog_dir, "python-quality", tags=["verification"])

        import ydk.cli.catalog_cmd as cmd

        monkeypatch.setattr(cmd, "_default_catalog_dir", lambda: catalog_dir)  # type: ignore[attr-defined]

        result = runner.invoke(app, ["--format", "json", "catalog", "search", "python"])
        assert result.exit_code == 0
        assert "python-quality" in result.output


class TestCatalogInstall:
    """Test ydk catalog install."""

    def test_install_success(self, tmp_path: Path, monkeypatch: object) -> None:
        catalog_dir = tmp_path / "catalog"
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _create_catalog_item(catalog_dir, "python-quality", tags=["verification"])

        import ydk.cli.catalog_cmd as cmd

        monkeypatch.setattr(cmd, "_default_catalog_dir", lambda: catalog_dir)  # type: ignore[attr-defined]
        monkeypatch.setattr(cmd, "_project_root", lambda: project_dir)  # type: ignore[attr-defined]

        result = runner.invoke(app, ["catalog", "install", "python-quality"])
        assert result.exit_code == 0
        assert "Installed" in result.output

    def test_install_not_found(self, tmp_path: Path, monkeypatch: object) -> None:
        catalog_dir = tmp_path / "catalog"
        catalog_dir.mkdir()

        import ydk.cli.catalog_cmd as cmd

        monkeypatch.setattr(cmd, "_default_catalog_dir", lambda: catalog_dir)  # type: ignore[attr-defined]
        monkeypatch.setattr(cmd, "_project_root", lambda: tmp_path)  # type: ignore[attr-defined]

        result = runner.invoke(app, ["catalog", "install", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestCatalogList:
    """Test ydk catalog list."""

    def test_list_empty(self, tmp_path: Path, monkeypatch: object) -> None:
        import ydk.cli.catalog_cmd as cmd

        monkeypatch.setattr(cmd, "_default_catalog_dir", lambda: tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setattr(cmd, "_project_root", lambda: tmp_path)  # type: ignore[attr-defined]

        result = runner.invoke(app, ["catalog", "list"])
        assert result.exit_code == 0
        assert "No catalog items" in result.output

    def test_list_installed_items(self, tmp_path: Path, monkeypatch: object) -> None:
        catalog_dir = tmp_path / "catalog"
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _create_catalog_item(catalog_dir, "item-a", tags=["verification"])
        _create_catalog_item(catalog_dir, "item-b", tags=["spec-reviewers"])

        backend = LocalCatalogBackend(catalog_dir=catalog_dir)
        backend.install("item-a", None, project_dir)
        backend.install("item-b", None, project_dir)

        import ydk.cli.catalog_cmd as cmd

        monkeypatch.setattr(cmd, "_default_catalog_dir", lambda: catalog_dir)  # type: ignore[attr-defined]
        monkeypatch.setattr(cmd, "_project_root", lambda: project_dir)  # type: ignore[attr-defined]

        result = runner.invoke(app, ["catalog", "list"])
        assert result.exit_code == 0
        assert "item-a" in result.output
        assert "item-b" in result.output


class TestCatalogInfo:
    """Test ydk catalog info."""

    def test_info_found(self, tmp_path: Path, monkeypatch: object) -> None:
        catalog_dir = tmp_path / "catalog"
        _create_catalog_item(catalog_dir, "my-item", tags=["verification"], description="A great tool")

        import ydk.cli.catalog_cmd as cmd

        monkeypatch.setattr(cmd, "_default_catalog_dir", lambda: catalog_dir)  # type: ignore[attr-defined]

        result = runner.invoke(app, ["catalog", "info", "my-item"])
        assert result.exit_code == 0
        assert "my-item" in result.output

    def test_info_not_found(self, tmp_path: Path, monkeypatch: object) -> None:
        catalog_dir = tmp_path / "catalog"
        catalog_dir.mkdir()

        import ydk.cli.catalog_cmd as cmd

        monkeypatch.setattr(cmd, "_default_catalog_dir", lambda: catalog_dir)  # type: ignore[attr-defined]

        result = runner.invoke(app, ["catalog", "info", "ghost"])
        assert result.exit_code == 1


class TestCatalogPublish:
    """Test ydk catalog publish."""

    def test_publish_success(self, tmp_path: Path, monkeypatch: object) -> None:
        catalog_dir = tmp_path / "catalog"
        source = tmp_path / "source" / "my-item"
        source.mkdir(parents=True)
        (source / "catalog.yaml").write_text(yaml.dump({"name": "my-item", "version": "1.0.0", "tags": []}))
        (source / "README.md").write_text("# My Item\n")

        import ydk.cli.catalog_cmd as cmd

        monkeypatch.setattr(cmd, "_default_catalog_dir", lambda: catalog_dir)  # type: ignore[attr-defined]

        result = runner.invoke(app, ["catalog", "publish", str(source)])
        assert result.exit_code == 0
        assert "Published" in result.output

    def test_publish_invalid(self, tmp_path: Path, monkeypatch: object) -> None:
        source = tmp_path / "source" / "bad"
        source.mkdir(parents=True)

        import ydk.cli.catalog_cmd as cmd

        monkeypatch.setattr(cmd, "_default_catalog_dir", lambda: tmp_path / "catalog")  # type: ignore[attr-defined]

        result = runner.invoke(app, ["catalog", "publish", str(source)])
        assert result.exit_code == 1


class TestCatalogUninstall:
    """Test ydk catalog uninstall."""

    def test_uninstall_success(self, tmp_path: Path, monkeypatch: object) -> None:
        catalog_dir = tmp_path / "catalog"
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _create_catalog_item(catalog_dir, "removable", tags=["verification"])

        backend = LocalCatalogBackend(catalog_dir=catalog_dir)
        backend.install("removable", None, project_dir)

        import ydk.cli.catalog_cmd as cmd

        monkeypatch.setattr(cmd, "_default_catalog_dir", lambda: catalog_dir)  # type: ignore[attr-defined]
        monkeypatch.setattr(cmd, "_project_root", lambda: project_dir)  # type: ignore[attr-defined]

        result = runner.invoke(app, ["catalog", "uninstall", "removable"])
        assert result.exit_code == 0
        assert "Uninstalled" in result.output

    def test_uninstall_not_installed(self, tmp_path: Path, monkeypatch: object) -> None:
        import ydk.cli.catalog_cmd as cmd

        monkeypatch.setattr(cmd, "_default_catalog_dir", lambda: tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setattr(cmd, "_project_root", lambda: tmp_path)  # type: ignore[attr-defined]

        result = runner.invoke(app, ["catalog", "uninstall", "ghost"])
        assert result.exit_code == 1

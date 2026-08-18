"""Tests for CatalogSearch — keyword fallback and ChromaDB integration."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from ydk.core.catalog_search import CatalogSearch


def _create_catalog_item(base: Path, name: str, tags: list[str] | None = None, description: str = "") -> Path:
    """Helper: create a minimal catalog item directory."""
    item_dir = base / name
    item_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "version": "0.1.0",
        "description": description or f"Test item {name}",
        "tags": tags or [],
    }
    (item_dir / "catalog.yaml").write_text(yaml.dump(manifest))
    (item_dir / "README.md").write_text(f"# {name}\n\n{description}\n")
    return item_dir


class TestCatalogSearchKeyword:
    """Keyword search fallback (no ChromaDB)."""

    def test_search_by_name(self, tmp_path: Path) -> None:
        _create_catalog_item(tmp_path, "python-quality", tags=["verification", "python"])
        _create_catalog_item(tmp_path, "hexagonal-architecture", tags=["verification", "architecture"])

        with patch("ydk.core.catalog_search._try_import_chromadb", return_value=None):
            searcher = CatalogSearch(tmp_path)
            results = searcher.search("python")

        assert len(results) >= 1
        names = [r[0] for r in results]
        assert "python-quality" in names

    def test_search_by_description(self, tmp_path: Path) -> None:
        _create_catalog_item(tmp_path, "my-tool", description="A fantastic linting tool for Go")

        with patch("ydk.core.catalog_search._try_import_chromadb", return_value=None):
            searcher = CatalogSearch(tmp_path)
            results = searcher.search("linting")

        assert len(results) >= 1
        assert results[0][0] == "my-tool"

    def test_search_no_results(self, tmp_path: Path) -> None:
        _create_catalog_item(tmp_path, "python-quality")

        with patch("ydk.core.catalog_search._try_import_chromadb", return_value=None):
            searcher = CatalogSearch(tmp_path)
            results = searcher.search("terraform")

        assert results == []

    def test_search_empty_catalog(self, tmp_path: Path) -> None:
        with patch("ydk.core.catalog_search._try_import_chromadb", return_value=None):
            searcher = CatalogSearch(tmp_path)
            results = searcher.search("anything")

        assert results == []

    def test_name_match_boosted(self, tmp_path: Path) -> None:
        _create_catalog_item(tmp_path, "python-quality", tags=["verification"], description="Python code quality")
        _create_catalog_item(tmp_path, "go-quality", tags=["verification"], description="Has python in readme")

        with patch("ydk.core.catalog_search._try_import_chromadb", return_value=None):
            searcher = CatalogSearch(tmp_path)
            results = searcher.search("python")

        # python-quality should rank higher due to name match boost
        assert results[0][0] == "python-quality"


class TestCatalogSearchChromaDB:
    """ChromaDB integration with mocked client."""

    def test_chromadb_search_used_when_available(self, tmp_path: Path) -> None:
        _create_catalog_item(tmp_path, "python-quality", tags=["verification"])

        mock_chromadb = MagicMock()
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chromadb.EphemeralClient.return_value = mock_client
        mock_collection.query.return_value = {
            "ids": [["python-quality"]],
            "distances": [[0.5]],
        }

        with patch("ydk.core.catalog_search._try_import_chromadb", return_value=mock_chromadb):
            searcher = CatalogSearch(tmp_path)
            results = searcher.search("python quality checks")

        assert len(results) == 1
        assert results[0][0] == "python-quality"
        # Score should be 1/(1+0.5) = 0.667
        assert 0.6 < results[0][1] < 0.7

    def test_chromadb_fallback_on_query_error(self, tmp_path: Path) -> None:
        _create_catalog_item(tmp_path, "python-quality", tags=["verification"])

        mock_chromadb = MagicMock()
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chromadb.EphemeralClient.return_value = mock_client
        mock_collection.query.side_effect = RuntimeError("ChromaDB error")

        with patch("ydk.core.catalog_search._try_import_chromadb", return_value=mock_chromadb):
            searcher = CatalogSearch(tmp_path)
            results = searcher.search("python")

        # Should fall back to keyword search
        assert len(results) >= 1


class TestCatalogSearchIndexItem:
    """Test incremental indexing."""

    def test_index_new_item(self, tmp_path: Path) -> None:
        with patch("ydk.core.catalog_search._try_import_chromadb", return_value=None):
            searcher = CatalogSearch(tmp_path)
            assert searcher.search("terraform") == []

            # Add a new item
            item = _create_catalog_item(tmp_path, "terraform-security", tags=["verification", "terraform"])
            searcher.index_item(item)

            results = searcher.search("terraform")
            assert len(results) >= 1
            assert results[0][0] == "terraform-security"

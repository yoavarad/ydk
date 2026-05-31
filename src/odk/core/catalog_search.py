"""Semantic search for catalog items — ChromaDB with BM25 keyword fallback."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def _try_import_chromadb() -> object | None:
    """Attempt to import chromadb; return the module or None."""
    try:
        import chromadb  # type: ignore[import-untyped]

        return chromadb
    except ImportError:
        return None


class CatalogSearch:
    """Semantic search over catalog items.

    Uses ChromaDB when available, otherwise falls back to keyword matching.
    """

    def __init__(self, catalog_dir: Path) -> None:
        self._catalog_dir = catalog_dir
        self._chromadb = _try_import_chromadb()
        self._collection: object | None = None
        self._keyword_index: dict[str, str] = {}  # name -> searchable text
        self._build_index()

    def _build_index(self) -> None:
        """Build the search index from all catalog items."""
        if not self._catalog_dir.exists():
            return

        items: list[tuple[str, str]] = []  # (name, text)
        for child in sorted(self._catalog_dir.iterdir()):
            if not child.is_dir():
                continue
            catalog_yaml = child / "catalog.yaml"
            if not catalog_yaml.exists():
                continue

            import yaml

            raw = yaml.safe_load(catalog_yaml.read_text())
            if not isinstance(raw, dict):
                continue

            name = raw.get("name", child.name)
            parts = [name, raw.get("description", "")]
            tags = raw.get("tags", [])
            if isinstance(tags, list):
                parts.extend(str(t) for t in tags)

            readme = child / "README.md"
            if readme.exists():
                parts.append(readme.read_text())

            text = " ".join(parts)
            items.append((name, text))
            self._keyword_index[name] = text.lower()

        if self._chromadb is not None and items:
            self._build_chromadb_index(items)

    def _build_chromadb_index(self, items: list[tuple[str, str]]) -> None:
        """Build ChromaDB collection from items."""
        try:
            client = self._chromadb.EphemeralClient()  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]
            collection = client.get_or_create_collection("odk_catalog")
            ids = [item[0] for item in items]
            documents = [item[1] for item in items]
            collection.upsert(ids=ids, documents=documents)
            self._collection = collection
        except Exception:
            logger.debug("ChromaDB indexing failed, falling back to keyword search", exc_info=True)
            self._collection = None

    def search(self, query: str, n_results: int = 10) -> list[tuple[str, float]]:
        """Search the catalog. Returns list of (item_name, relevance_score)."""
        if self._collection is not None:
            return self._search_chromadb(query, n_results)
        return self._search_keyword(query, n_results)

    def _search_chromadb(self, query: str, n_results: int) -> list[tuple[str, float]]:
        """Semantic search via ChromaDB."""
        try:
            actual_n = min(n_results, len(self._keyword_index))
            if actual_n == 0:
                return []
            results = self._collection.query(query_texts=[query], n_results=actual_n)  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]
            ids = results.get("ids", [[]])[0]
            distances = results.get("distances", [[]])[0]
            # ChromaDB returns distances (lower = better), convert to scores
            return [(name, 1.0 / (1.0 + dist)) for name, dist in zip(ids, distances, strict=True)]
        except Exception:
            logger.debug("ChromaDB search failed, falling back to keyword", exc_info=True)
            return self._search_keyword(query, n_results)

    def _search_keyword(self, query: str, n_results: int) -> list[tuple[str, float]]:
        """Simple keyword matching fallback."""
        query_lower = query.lower()
        query_terms = query_lower.split()
        scored: list[tuple[str, float]] = []
        for name, text in self._keyword_index.items():
            score = 0.0
            for term in query_terms:
                if term in text:
                    score += 1.0
                if term in name.lower():
                    score += 2.0  # boost name matches
            if score > 0:
                scored.append((name, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:n_results]

    def index_item(self, item_path: Path) -> None:
        """Add or update a single item in the index."""
        import yaml

        catalog_yaml = item_path / "catalog.yaml"
        if not catalog_yaml.exists():
            return

        raw = yaml.safe_load(catalog_yaml.read_text())
        if not isinstance(raw, dict):
            return

        name = raw.get("name", item_path.name)
        parts = [name, raw.get("description", "")]
        tags = raw.get("tags", [])
        if isinstance(tags, list):
            parts.extend(str(t) for t in tags)

        readme = item_path / "README.md"
        if readme.exists():
            parts.append(readme.read_text())

        text = " ".join(parts)
        self._keyword_index[name] = text.lower()

        if self._collection is not None:
            try:
                self._collection.upsert(ids=[name], documents=[text])  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]
            except Exception:
                logger.debug("Failed to update ChromaDB index for %s", name, exc_info=True)

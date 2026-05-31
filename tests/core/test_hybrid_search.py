"""Tests for hybrid search (RRF fusion of vector + BM25)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from odk.core.bm25_index import BM25Index
from odk.core.memory import MemoryEngine


class TestRRFFusion:
    """Test Reciprocal Rank Fusion produces correct merged ordering."""

    def test_rrf_merges_two_ranked_lists(self) -> None:
        engine = MemoryEngine(chroma_path=Path("/tmp/unused"))

        vector_results = [
            {"source": "a.md", "snippet": "a", "section": "s", "score": 0.9, "collection": "c"},
            {"source": "b.md", "snippet": "b", "section": "s", "score": 0.8, "collection": "c"},
            {"source": "c.md", "snippet": "c", "section": "s", "score": 0.7, "collection": "c"},
        ]
        bm25_results = [
            ("b.md#s", 5.0),
            ("d.md#s", 4.0),
            ("a.md#s", 3.0),
        ]
        bm25_snippets = {
            "b.md#s": {"source": "b.md", "snippet": "b", "section": "s", "collection": "c"},
            "d.md#s": {"source": "d.md", "snippet": "d", "section": "s", "collection": "c"},
            "a.md#s": {"source": "a.md", "snippet": "a", "section": "s", "collection": "c"},
        }

        fused = engine._rrf_fuse(vector_results, bm25_results, bm25_snippets, k=60)

        # b.md appears rank 2 in vector (1/(60+2)) and rank 1 in bm25 (1/(60+1))
        # a.md appears rank 1 in vector (1/(60+1)) and rank 3 in bm25 (1/(60+3))
        # Both should score higher than items in only one list
        doc_sources = [r["source"] for r in fused]
        # a and b should be in top positions (they appear in both lists)
        assert "a.md" in doc_sources[:3]
        assert "b.md" in doc_sources[:3]

    def test_rrf_item_in_both_lists_ranks_higher(self) -> None:
        engine = MemoryEngine(chroma_path=Path("/tmp/unused"))

        vector_results = [
            {"source": "only_vector.md", "snippet": "v", "section": "s", "score": 0.95, "collection": "c"},
            {"source": "both.md", "snippet": "b", "section": "s", "score": 0.5, "collection": "c"},
        ]
        bm25_results = [
            ("only_bm25.md#s", 5.0),
            ("both.md#s", 4.0),
        ]
        bm25_snippets = {
            "only_bm25.md#s": {"source": "only_bm25.md", "snippet": "bm", "section": "s", "collection": "c"},
            "both.md#s": {"source": "both.md", "snippet": "b", "section": "s", "collection": "c"},
        }

        fused = engine._rrf_fuse(vector_results, bm25_results, bm25_snippets, k=60)
        doc_sources = [r["source"] for r in fused]

        # "both.md" appears in both lists, so it should rank #1
        assert doc_sources[0] == "both.md"


class TestSearchModes:
    """Test search_mode parameter controls which search methods run."""

    def test_vector_mode_skips_bm25(self) -> None:
        engine = MemoryEngine(chroma_path=Path("/tmp/unused"))

        # Mock _vector_search to return results
        engine._vector_search = MagicMock(  # type: ignore[assignment]
            return_value=[
                {"source": "a.md", "snippet": "a", "section": "s", "score": 0.9, "collection": "c"},
            ]
        )
        engine._bm25_search = MagicMock(return_value=([], {}))  # type: ignore[assignment]

        results = engine.search("test query", search_mode="vector")
        engine._vector_search.assert_called_once()
        engine._bm25_search.assert_not_called()
        assert len(results) == 1

    def test_keyword_mode_skips_vector(self) -> None:
        engine = MemoryEngine(chroma_path=Path("/tmp/unused"))

        engine._vector_search = MagicMock(return_value=[])  # type: ignore[assignment]
        engine._bm25_search = MagicMock(  # type: ignore[assignment]
            return_value=(
                [("a.md#s", 5.0)],
                {"a.md#s": {"source": "a.md", "snippet": "a", "section": "s", "collection": "c"}},
            )
        )

        results = engine.search("test query", search_mode="keyword")
        engine._vector_search.assert_not_called()
        engine._bm25_search.assert_called_once()
        assert len(results) == 1

    def test_hybrid_mode_runs_both(self) -> None:
        engine = MemoryEngine(chroma_path=Path("/tmp/unused"))

        engine._vector_search = MagicMock(  # type: ignore[assignment]
            return_value=[
                {"source": "a.md", "snippet": "a", "section": "s", "score": 0.9, "collection": "c"},
            ]
        )
        engine._bm25_search = MagicMock(  # type: ignore[assignment]
            return_value=(
                [("b.md#s", 5.0)],
                {"b.md#s": {"source": "b.md", "snippet": "b", "section": "s", "collection": "c"}},
            )
        )
        engine._rrf_fuse = MagicMock(  # type: ignore[assignment]
            return_value=[
                {"source": "a.md", "snippet": "a", "section": "s", "score": 0.9, "collection": "c"},
                {"source": "b.md", "snippet": "b", "section": "s", "score": 0.5, "collection": "c"},
            ]
        )

        results = engine.search("test query", search_mode="hybrid")
        engine._vector_search.assert_called_once()
        engine._bm25_search.assert_called_once()
        engine._rrf_fuse.assert_called_once()
        assert len(results) == 2

    def test_default_mode_is_hybrid(self) -> None:
        engine = MemoryEngine(chroma_path=Path("/tmp/unused"))

        engine._vector_search = MagicMock(return_value=[])  # type: ignore[assignment]
        engine._bm25_search = MagicMock(return_value=([], {}))  # type: ignore[assignment]
        engine._rrf_fuse = MagicMock(return_value=[])  # type: ignore[assignment]

        engine.search("test query")
        engine._vector_search.assert_called_once()
        engine._bm25_search.assert_called_once()


class TestBM25IndexMaintenance:
    """Test that BM25 index is built alongside ChromaDB during indexing."""

    def test_index_file_updates_bm25(self, tmp_path) -> None:
        engine = MemoryEngine(chroma_path=tmp_path / "chroma")
        bm25_path = tmp_path / "bm25_index.json"
        engine._bm25_index_path = bm25_path

        # Mock ChromaDB parts
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": []}
        engine._get_collection = MagicMock(return_value=mock_collection)  # type: ignore[assignment]

        # Create a test file
        md_file = tmp_path / "test.md"
        md_file.write_text("## Section\nSome searchable content here.")

        engine.index_file(md_file, "test_col")

        # BM25 index should exist
        bm25 = BM25Index(index_path=bm25_path)
        results = bm25.search("searchable content", n_results=5)
        assert len(results) >= 1

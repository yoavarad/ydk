"""Tests for progressive retrieval."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from odk.core.memory import MemoryEngine


class TestCompactIndex:
    def test_format(self) -> None:
        r = [{"source": "a.md", "snippet": "JWT", "section": "Auth", "score": 0.95, "collection": "d"}]
        c = MemoryEngine._to_compact_index(r)
        assert c[0]["id"] == "a.md#Auth"
        assert c[0]["title"] == "Auth"
        assert c[0]["score"] == 0.95
        assert "snippet_preview" in c[0]

    def test_truncates_long(self) -> None:
        r = [{"source": "l.md", "snippet": "x" * 300, "section": "S", "score": 0.5, "collection": "c"}]
        c = MemoryEngine._to_compact_index(r)
        assert c[0]["snippet_preview"].endswith("...")
        assert len(c[0]["snippet_preview"]) == 153

    def test_short_unchanged(self) -> None:
        r = [{"source": "s.md", "snippet": "Short", "section": "I", "score": 0.9, "collection": "c"}]
        assert MemoryEngine._to_compact_index(r)[0]["snippet_preview"] == "Short"

    def test_required_keys(self) -> None:
        r = [{"source": "t.md", "snippet": "c", "section": "s", "score": 0.5, "collection": "c"}]
        assert set(MemoryEngine._to_compact_index(r)[0].keys()) == {"id", "title", "score", "snippet_preview"}


class TestSearchDepth:
    def test_index_returns_compact(self) -> None:
        e = MemoryEngine(chroma_path=Path("/tmp/unused"))
        e._vector_search = lambda q, n_results=10, collection_name=None: [
            {"source": "t.md", "snippet": "F", "section": "S", "score": 0.9, "collection": "d"}
        ]  # type: ignore[assignment]
        r = e.search("q", search_mode="vector", depth="index")
        assert "snippet_preview" in r[0]
        assert "snippet" not in r[0]

    def test_summary_truncates(self) -> None:
        e = MemoryEngine(chroma_path=Path("/tmp/unused"))
        e._vector_search = lambda q, n_results=10, collection_name=None: [
            {"source": "t.md", "snippet": "x" * 500, "section": "S", "score": 0.9, "collection": "d"}
        ]  # type: ignore[assignment]
        r = e.search("q", search_mode="vector", depth="summary")
        assert r[0]["snippet"].endswith("...")
        assert len(r[0]["snippet"]) == 203

    def test_full_default(self) -> None:
        e = MemoryEngine(chroma_path=Path("/tmp/unused"))
        orig = "Full content"
        e._vector_search = lambda q, n_results=10, collection_name=None: [
            {"source": "t.md", "snippet": orig, "section": "S", "score": 0.9, "collection": "d"}
        ]  # type: ignore[assignment]
        assert e.search("q", search_mode="vector")[0]["snippet"] == orig


class TestGetMemoryDetails:
    def test_retrieves(self) -> None:
        e = MemoryEngine(chroma_path=Path("/tmp/unused"))
        mc = MagicMock()
        mc.get.return_value = {
            "ids": ["m1"],
            "documents": ["Full"],
            "metadatas": [
                {
                    "source_file": "t.md",
                    "section": "i",
                    "collection": "extractions",
                    "created_at": "2025-01-01T00:00:00Z",
                    "source_type": "user-stated",
                    "valid_from": "2025-01-01T00:00:00Z",
                    "valid_until": "",
                }
            ],
        }
        e._get_collection = MagicMock(return_value=mc)  # type: ignore[assignment]
        d = e.get_memory_details(["m1"])
        assert d[0]["id"] == "m1"
        assert d[0]["valid_from"] == "2025-01-01T00:00:00Z"

    def test_empty_for_missing(self) -> None:
        e = MemoryEngine(chroma_path=Path("/tmp/unused"))
        mc = MagicMock()
        mc.get.return_value = {"ids": [], "documents": [], "metadatas": []}
        e._get_collection = MagicMock(return_value=mc)  # type: ignore[assignment]
        assert e.get_memory_details(["x"]) == []


class TestBootstrapCompact:
    def test_compact_format(self) -> None:
        e = MemoryEngine(chroma_path=Path("/tmp/unused"))
        n = 0

        def ms(query, n_results=10, collection_name=None, search_mode="hybrid", depth="full", include_expired=False):
            nonlocal n
            n += 1
            return [{"source": f"d-{n}.md", "snippet": "C", "section": "i", "score": 0.8, "collection": "t"}]

        e.search = ms  # type: ignore[assignment]
        r = e.bootstrap("task", ["ref1"], compact=True)
        assert "snippet_preview" in r[0]

    def test_non_compact(self) -> None:
        e = MemoryEngine(chroma_path=Path("/tmp/unused"))

        def ms(query, n_results=10, collection_name=None, search_mode="hybrid", depth="full", include_expired=False):
            return [{"source": "d.md", "snippet": "Full", "section": "i", "score": 0.8, "collection": "t"}]

        e.search = ms  # type: ignore[assignment]
        r = e.bootstrap("task", [])
        assert "snippet" in r[0]
        assert "snippet_preview" not in r[0]

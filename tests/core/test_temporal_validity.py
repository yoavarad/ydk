"""Tests for temporal validity."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from odk.core.memory import MemoryEngine
from odk.models.memory import ExtractedMemoryModel


class TestTemporalFields:
    def test_defaults_none(self) -> None:
        m = ExtractedMemoryModel(memory_type="discovery", content="test")
        assert m.valid_from is None
        assert m.valid_until is None

    def test_set_values(self) -> None:
        m = ExtractedMemoryModel(
            memory_type="discovery",
            content="test",
            valid_from="2025-01-01T00:00:00Z",
            valid_until="2025-12-31T23:59:59Z",
        )
        assert m.valid_from == "2025-01-01T00:00:00Z"
        assert m.valid_until == "2025-12-31T23:59:59Z"


class TestTemporalStorage:
    def test_stores_valid_from_valid_until(self) -> None:
        e = MemoryEngine(chroma_path=Path("/tmp/unused"))
        mc = MagicMock()
        e._get_collection = MagicMock(return_value=mc)  # type: ignore[assignment]
        e.add_extraction(
            task_id="T-001",
            extraction_type="decision",
            content="PG",
            valid_from="2025-01-01T00:00:00Z",
            valid_until="2025-06-30T23:59:59Z",
        )
        meta = (
            mc.add.call_args.kwargs["metadatas"][0] if mc.add.call_args.kwargs else mc.add.call_args[1]["metadatas"][0]
        )
        assert meta["valid_from"] == "2025-01-01T00:00:00Z"
        assert meta["valid_until"] == "2025-06-30T23:59:59Z"

    def test_defaults_valid_from_to_now(self) -> None:
        e = MemoryEngine(chroma_path=Path("/tmp/unused"))
        mc = MagicMock()
        e._get_collection = MagicMock(return_value=mc)  # type: ignore[assignment]
        e.add_extraction(task_id="T-002", extraction_type="discovery", content="Found")
        meta = (
            mc.add.call_args.kwargs["metadatas"][0] if mc.add.call_args.kwargs else mc.add.call_args[1]["metadatas"][0]
        )
        assert meta["valid_from"] != ""
        assert meta["valid_until"] == ""


class TestExpiredFiltering:
    def test_removes_past(self) -> None:
        r = [
            {"source": "c.md", "snippet": "c", "valid_until": ""},
            {"source": "e.md", "snippet": "e", "valid_until": "2020-01-01T00:00:00Z"},
            {"source": "f.md", "snippet": "f", "valid_until": "2099-12-31T23:59:59Z"},
        ]
        f = MemoryEngine._filter_expired(r)
        s = [x["source"] for x in f]
        assert "c.md" in s
        assert "f.md" in s
        assert "e.md" not in s

    def test_keeps_no_valid_until(self) -> None:
        r = [{"source": "a.md", "snippet": "a"}, {"source": "b.md", "snippet": "b", "valid_until": ""}]
        assert len(MemoryEngine._filter_expired(r)) == 2

    def test_search_excludes_expired(self) -> None:
        e = MemoryEngine(chroma_path=Path("/tmp/unused"))
        e._vector_search = lambda q, n_results=10, collection_name=None: [
            {"source": "v.md", "snippet": "v", "section": "s", "score": 0.9, "collection": "c", "valid_until": ""},
            {
                "source": "e.md",
                "snippet": "e",
                "section": "s",
                "score": 0.8,
                "collection": "c",
                "valid_until": "2020-01-01T00:00:00Z",
            },
        ]  # type: ignore[assignment]
        r = e.search("q", search_mode="vector")
        assert len(r) == 1
        assert r[0]["source"] == "v.md"

    def test_include_expired_flag(self) -> None:
        e = MemoryEngine(chroma_path=Path("/tmp/unused"))
        e._vector_search = lambda q, n_results=10, collection_name=None: [
            {"source": "v.md", "snippet": "v", "section": "s", "score": 0.9, "collection": "c", "valid_until": ""},
            {
                "source": "e.md",
                "snippet": "e",
                "section": "s",
                "score": 0.8,
                "collection": "c",
                "valid_until": "2020-01-01T00:00:00Z",
            },
        ]  # type: ignore[assignment]
        assert len(e.search("q", search_mode="vector", include_expired=True)) == 2


class TestContradictionSetsValidUntil:
    def test_sets_valid_until(self) -> None:
        e = MemoryEngine(chroma_path=Path("/tmp/unused"))
        mc = MagicMock()
        mc.get.side_effect = [
            {
                "ids": ["old"],
                "documents": ["We use PostgreSQL"],
                "metadatas": [{"concepts": "database,postgresql", "valid_until": ""}],
            },
            {"ids": ["old"], "metadatas": [{"concepts": "database,postgresql", "valid_until": ""}]},
        ]
        e._get_collection = MagicMock(return_value=mc)  # type: ignore[assignment]
        from odk.core.contradiction_detector import ContradictionDetector

        class FL:
            def judge_contradiction(self, new_text, old_text):
                return "changed"

        det = ContradictionDetector(similarity_threshold=0.3, llm=FL())
        e.add_extraction(
            task_id="T-003",
            extraction_type="decision",
            content="We use SQLite for the database",
            concepts=["database", "sqlite"],
            contradiction_detector=det,
        )
        u = mc.update.call_args_list
        assert len(u) >= 1
        meta = u[0].kwargs.get("metadatas") or u[0][1].get("metadatas")
        assert meta[0]["valid_until"] != ""

"""Tests for memory consolidation — duplicate detection and merging."""

from __future__ import annotations

from ydk.core.memory_consolidation import MemoryConsolidator
from ydk.models.consolidation import ConsolidationReport, DuplicateGroup


class FakeVectorStore:
    """In-memory vector store for testing consolidation logic."""

    def __init__(self, docs: list[dict] | None = None, similarities: dict[str, list[dict]] | None = None) -> None:
        self._docs = {d["id"]: d for d in (docs or [])}
        self._similarities = similarities or {}
        self.deleted_ids: list[str] = []
        self.updated_metadata: dict[str, dict] = {}

    def get_all(self, collection: str) -> list[dict]:
        return list(self._docs.values())

    def query_similar(self, collection: str, document: str, n_results: int) -> list[dict]:
        return self._similarities.get(document, [])

    def delete(self, collection: str, ids: list[str]) -> None:
        self.deleted_ids.extend(ids)
        for doc_id in ids:
            self._docs.pop(doc_id, None)

    def update_metadata(self, collection: str, doc_id: str, metadata: dict) -> None:
        self.updated_metadata[doc_id] = metadata


class TestFindDuplicates:
    def test_finds_similar_pairs(self) -> None:
        docs = [
            {"id": "a", "text": "JWT auth pattern", "topic": "auth"},
            {"id": "b", "text": "JWT authentication approach", "topic": "auth"},
        ]
        similarities = {
            "JWT auth pattern": [
                {"id": "a", "similarity": 1.0},
                {"id": "b", "similarity": 0.95},
            ],
            "JWT authentication approach": [
                {"id": "b", "similarity": 1.0},
                {"id": "a", "similarity": 0.95},
            ],
        }
        store = FakeVectorStore(docs=docs, similarities=similarities)
        consolidator = MemoryConsolidator(store=store)
        groups = consolidator.find_duplicates(threshold=0.9)
        assert len(groups) == 1
        assert groups[0].canonical_id == "a"
        assert groups[0].duplicate_ids == ["b"]
        assert groups[0].similarity >= 0.9

    def test_no_duplicates_below_threshold(self) -> None:
        docs = [
            {"id": "a", "text": "auth pattern", "topic": "auth"},
            {"id": "b", "text": "database schema", "topic": "db"},
        ]
        similarities = {
            "auth pattern": [{"id": "b", "similarity": 0.3}],
            "database schema": [{"id": "a", "similarity": 0.3}],
        }
        store = FakeVectorStore(docs=docs, similarities=similarities)
        consolidator = MemoryConsolidator(store=store)
        groups = consolidator.find_duplicates(threshold=0.9)
        assert groups == []

    def test_empty_store(self) -> None:
        store = FakeVectorStore(docs=[])
        consolidator = MemoryConsolidator(store=store)
        groups = consolidator.find_duplicates()
        assert groups == []


class TestMergeDuplicates:
    def test_deletes_duplicates(self) -> None:
        store = FakeVectorStore(
            docs=[
                {"id": "a", "text": "keep"},
                {"id": "b", "text": "remove"},
                {"id": "c", "text": "remove too"},
            ]
        )
        groups = [DuplicateGroup(canonical_id="a", duplicate_ids=["b", "c"], similarity=0.95)]
        consolidator = MemoryConsolidator(store=store)
        removed = consolidator.merge_duplicates(groups)
        assert removed == 2
        assert "b" in store.deleted_ids
        assert "c" in store.deleted_ids
        assert "b" in store.updated_metadata
        assert store.updated_metadata["b"]["superseded_by"] == "a"

    def test_dry_run_does_not_delete(self) -> None:
        store = FakeVectorStore(docs=[{"id": "a", "text": "keep"}, {"id": "b", "text": "remove"}])
        groups = [DuplicateGroup(canonical_id="a", duplicate_ids=["b"], similarity=0.95)]
        consolidator = MemoryConsolidator(store=store)
        removed = consolidator.merge_duplicates(groups, dry_run=True)
        assert removed == 1
        assert store.deleted_ids == []
        assert store.updated_metadata == {}


class TestAudit:
    def test_audit_report_structure(self) -> None:
        docs = [
            {"id": "a", "text": "recent", "topic": "auth", "created_at": "2026-04-28T00:00:00Z"},
            {"id": "b", "text": "also recent", "topic": "auth", "created_at": "2026-04-28T00:00:00Z"},
        ]
        similarities = {
            "recent": [{"id": "b", "similarity": 0.5}],
            "also recent": [{"id": "a", "similarity": 0.5}],
        }
        store = FakeVectorStore(docs=docs, similarities=similarities)
        consolidator = MemoryConsolidator(store=store)
        report = consolidator.audit()
        assert isinstance(report, ConsolidationReport)
        assert report.total_memories == 2
        assert report.duplicate_count == 0
        assert report.stale_count == 0

    def test_audit_counts_stale(self) -> None:
        docs = [{"id": "a", "text": "old", "topic": "auth", "created_at": "2025-01-01T00:00:00Z"}]
        store = FakeVectorStore(docs=docs, similarities={"old": []})
        consolidator = MemoryConsolidator(store=store)
        report = consolidator.audit()
        assert report.stale_count == 1

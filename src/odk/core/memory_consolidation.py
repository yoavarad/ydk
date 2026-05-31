"""Memory consolidation — duplicate detection and merging."""

from __future__ import annotations

import time
from typing import Protocol

from odk.models.consolidation import ConsolidationReport, ConsolidationResult, DuplicateGroup


class VectorStore(Protocol):
    """Minimal vector-store interface for consolidation (ChromaDB at boundary)."""

    def get_all(self, collection: str) -> list[dict]:
        """Return all documents with metadata from a collection."""
        ...

    def query_similar(self, collection: str, document: str, n_results: int) -> list[dict]:
        """Return similar documents with similarity scores."""
        ...

    def delete(self, collection: str, ids: list[str]) -> None:
        """Delete documents by ID."""
        ...

    def update_metadata(self, collection: str, doc_id: str, metadata: dict) -> None:
        """Update metadata for a document."""
        ...


class MemoryConsolidator:
    """Finds and merges duplicate memories in a vector store."""

    def __init__(self, store: VectorStore) -> None:
        self._store = store

    def find_duplicates(self, threshold: float = 0.9, collection: str = "extractions") -> list[DuplicateGroup]:
        """Find semantically similar memory pairs using vector similarity."""
        all_docs = self._store.get_all(collection)
        if not all_docs:
            return []
        seen: set[str] = set()
        groups: list[DuplicateGroup] = []
        for doc in all_docs:
            doc_id = doc["id"]
            if doc_id in seen:
                continue
            similar = self._store.query_similar(collection, doc["text"], n_results=10)
            duplicates: list[str] = []
            for sim in similar:
                sim_id = sim["id"]
                if sim_id == doc_id or sim_id in seen:
                    continue
                if sim.get("similarity", 0.0) >= threshold:
                    duplicates.append(sim_id)
                    seen.add(sim_id)
            if duplicates:
                seen.add(doc_id)
                groups.append(
                    DuplicateGroup(
                        canonical_id=doc_id,
                        duplicate_ids=duplicates,
                        similarity=max(s.get("similarity", 0.0) for s in similar if s["id"] in duplicates),
                        topic=doc.get("topic", ""),
                    )
                )
        return groups

    def merge_duplicates(
        self, groups: list[DuplicateGroup], dry_run: bool = False, collection: str = "extractions"
    ) -> int:
        """Merge duplicates: keep canonical, mark others as superseded."""
        removed = 0
        for group in groups:
            if dry_run:
                removed += len(group.duplicate_ids)
                continue
            for dup_id in group.duplicate_ids:
                self._store.update_metadata(collection, dup_id, {"superseded_by": group.canonical_id})
            self._store.delete(collection, group.duplicate_ids)
            removed += len(group.duplicate_ids)
        return removed

    def consolidate_topic(
        self, topic: str, threshold: float = 0.9, collection: str = "extractions"
    ) -> ConsolidationResult:
        """Find and merge all duplicates for a topic."""
        all_groups = self.find_duplicates(threshold=threshold, collection=collection)
        topic_groups = [g for g in all_groups if topic.lower() in g.topic.lower()] if topic else all_groups
        merged = self.merge_duplicates(topic_groups, collection=collection)
        kept = [g.canonical_id for g in topic_groups]
        removed = [dup_id for g in topic_groups for dup_id in g.duplicate_ids]
        return ConsolidationResult(
            topic=topic, groups_found=len(topic_groups), duplicates_merged=merged, kept_ids=kept, removed_ids=removed
        )

    def audit(self, collection: str = "extractions") -> ConsolidationReport:
        """Report on memory health: duplicate count, stale count, total."""
        all_docs = self._store.get_all(collection)
        total = len(all_docs)
        groups = self.find_duplicates(collection=collection)
        duplicate_count = sum(len(g.duplicate_ids) for g in groups)
        now = time.time()
        stale_threshold = 90 * 86400
        stale_count = 0
        for doc in all_docs:
            created_at = doc.get("created_at", "")
            if created_at:
                try:
                    created_epoch = time.mktime(time.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
                    if (now - created_epoch) > stale_threshold:
                        stale_count += 1
                except (ValueError, OverflowError):
                    pass
        return ConsolidationReport(
            total_memories=total, duplicate_count=duplicate_count, stale_count=stale_count, groups=groups
        )

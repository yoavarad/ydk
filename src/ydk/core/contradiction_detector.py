"""Contradiction detection for memory writes."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ydk.models.memory import ExtractedMemoryModel


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal protocol for an LLM that judges contradictions."""

    def judge_contradiction(self, new_text: str, old_text: str) -> str | None:
        """Return a reason string if the two texts contradict, else None."""
        ...


@dataclass
class Contradiction:
    """A detected contradiction between a new memory and an existing one."""

    old_memory_id: str
    old_content: str
    reason: str


@dataclass
class ContradictionDetector:
    """Detect contradictions between new and existing memories."""

    similarity_threshold: float = 0.6
    llm: LLMProvider | None = None
    _invalidated: dict[str, str] = field(default_factory=dict)

    def check(self, new_memory: ExtractedMemoryModel, existing: list[dict]) -> list[Contradiction]:
        """Check *new_memory* against *existing* memories for contradictions."""
        if self.llm is None:
            return []
        candidates = self._find_candidates(new_memory, existing)
        contradictions: list[Contradiction] = []
        for entry in candidates:
            reason = self.llm.judge_contradiction(new_memory.content, entry["content"])
            if reason:
                contradictions.append(
                    Contradiction(old_memory_id=entry["id"], old_content=entry["content"], reason=reason)
                )
        return contradictions

    def invalidate(self, memory_id: str) -> None:
        """Mark a memory as invalidated."""
        self._invalidated[memory_id] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def is_invalidated(self, memory_id: str) -> bool:
        """Return True if *memory_id* has been invalidated."""
        return memory_id in self._invalidated

    def get_invalidated_at(self, memory_id: str) -> str | None:
        """Return the invalidation timestamp, or None."""
        return self._invalidated.get(memory_id)

    def _find_candidates(self, new_memory: ExtractedMemoryModel, existing: list[dict]) -> list[dict]:
        """Find existing memories that might contradict *new_memory*."""
        new_concepts = {c.lower() for c in new_memory.concepts}
        new_words = set(new_memory.content.lower().split())
        candidates: list[dict] = []
        for entry in existing:
            old_concepts = {c.lower() for c in entry.get("concepts", [])}
            old_words = set(entry.get("content", "").lower().split())
            if new_concepts and old_concepts:
                overlap = len(new_concepts & old_concepts) / max(len(new_concepts | old_concepts), 1)
                if overlap >= self.similarity_threshold:
                    candidates.append(entry)
                    continue
            if new_words and old_words:
                word_overlap = len(new_words & old_words) / max(len(new_words | old_words), 1)
                if word_overlap >= self.similarity_threshold:
                    candidates.append(entry)
        return candidates

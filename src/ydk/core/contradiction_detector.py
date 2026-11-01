"""Contradiction detection for memory writes."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel

from ydk.core.llm_provider import SubagentHandoff

if TYPE_CHECKING:
    from pathlib import Path

    from ydk.core.llm_provider import StructuredLLMProvider
    from ydk.models.memory import ExtractedMemoryModel


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal protocol for an LLM that judges contradictions."""

    def judge_contradiction(self, new_text: str, old_text: str) -> str | None:
        """Return a reason string if the two texts contradict, else None."""
        ...


class ContradictionVerdict(BaseModel):
    """Structured LLM answer for one (new, old) memory pair."""

    contradicts: bool
    reason: str = ""


class ProviderContradictionJudge:
    """Adapt a StructuredLLMProvider to the ``judge_contradiction`` protocol.

    Subagent handoffs are collected (the pair is treated as undecided) so one
    ``flush()`` can raise a single handoff covering every pending judgement.
    """

    def __init__(self, provider: StructuredLLMProvider) -> None:
        self._provider = provider
        self._cache: dict[tuple[str, str], str | None] = {}
        self._pending: list[Path] = []

    def judge_contradiction(self, new_text: str, old_text: str) -> str | None:
        """Return a reason if *new_text* contradicts *old_text*, else None."""
        key = (new_text, old_text)
        if key in self._cache:
            return self._cache[key]
        prompt = (
            "Decide whether the NEW memory contradicts the OLD memory (the old one is no longer true). "
            f"OLD: {old_text} | NEW: {new_text} | "
            "Answer with contradicts (bool) and a short reason."
        )
        try:
            verdict = self._provider.invoke_structured(prompt, ContradictionVerdict)
        except SubagentHandoff as handoff:
            self._pending.extend(p for p in handoff.request_paths if p not in self._pending)
            return None
        result = (verdict.reason or "contradicts") if verdict.contradicts else None
        self._cache[key] = result
        return result

    def flush(self) -> None:
        """Raise one ``SubagentHandoff`` for all collected requests; no-op if none."""
        if not self._pending:
            return
        paths, self._pending = self._pending, []
        raise SubagentHandoff(paths)


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

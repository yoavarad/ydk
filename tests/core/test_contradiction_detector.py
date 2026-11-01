"""Tests for ContradictionDetector."""

from __future__ import annotations

import pytest

from ydk.core.contradiction_detector import Contradiction, ContradictionDetector, LLMProvider
from ydk.models.memory import ExtractedMemoryModel


class FakeLLM:
    """Fake LLM for testing."""

    def __init__(self, contradicts: bool = True, reason: str = "Contradicts") -> None:
        self._contradicts = contradicts
        self._reason = reason

    def judge_contradiction(self, new_text: str, old_text: str) -> str | None:
        """Return reason if configured to contradict."""
        return self._reason if self._contradicts else None


class TestContradictionDetection:
    def test_detects_with_concept_overlap(self) -> None:
        d = ContradictionDetector(similarity_threshold=0.3, llm=FakeLLM(reason="changed"))
        m = ExtractedMemoryModel(memory_type="decision", content="SQLite for db", concepts=["database", "sqlite"])
        e = [{"id": "m1", "content": "PostgreSQL for db", "concepts": ["database", "postgresql"]}]
        c = d.check(m, e)
        assert len(c) == 1
        assert c[0].old_memory_id == "m1"

    def test_no_contradiction_when_llm_says_no(self) -> None:
        d = ContradictionDetector(similarity_threshold=0.3, llm=FakeLLM(contradicts=False))
        m = ExtractedMemoryModel(memory_type="discovery", content="SQLite good", concepts=["db", "test"])
        e = [{"id": "m1", "content": "PG good", "concepts": ["db", "prod"]}]
        assert d.check(m, e) == []

    def test_no_candidates_below_threshold(self) -> None:
        d = ContradictionDetector(similarity_threshold=0.9, llm=FakeLLM())
        m = ExtractedMemoryModel(memory_type="discovery", content="sky blue", concepts=["weather"])
        e = [{"id": "m1", "content": "Redis fast", "concepts": ["cache"]}]
        assert d.check(m, e) == []

    def test_word_overlap_fallback(self) -> None:
        d = ContradictionDetector(similarity_threshold=0.3, llm=FakeLLM(reason="Changed"))
        m = ExtractedMemoryModel(memory_type="decision", content="use redis for cache layer", concepts=[])
        e = [{"id": "m2", "content": "use memcached for cache layer", "concepts": []}]
        assert len(d.check(m, e)) == 1


class TestInvalidation:
    def test_invalidate_marks(self) -> None:
        d = ContradictionDetector()
        d.invalidate("m1")
        assert d.is_invalidated("m1")
        assert d.get_invalidated_at("m1") is not None

    def test_not_invalidated_default(self) -> None:
        assert not ContradictionDetector().is_invalidated("m1")


class TestGracefulSkip:
    def test_empty_without_llm(self) -> None:
        d = ContradictionDetector(llm=None)
        m = ExtractedMemoryModel(memory_type="decision", content="SQLite", concepts=["db"])
        assert d.check(m, [{"id": "m1", "content": "PG", "concepts": ["db"]}]) == []

    def test_default_no_llm(self) -> None:
        assert ContradictionDetector().llm is None


class TestLLMProtocol:
    def test_satisfies_protocol(self) -> None:
        assert isinstance(FakeLLM(), LLMProvider)

    def test_dataclass_fields(self) -> None:
        c = Contradiction(old_memory_id="m1", old_content="old", reason="ch")
        assert c.old_memory_id == "m1"


class _FakeStructured:
    """Fake StructuredLLMProvider (LLM boundary)."""

    def __init__(self, verdicts: dict[str, tuple[bool, str]]) -> None:
        self.verdicts = verdicts
        self.calls = 0

    def invoke_structured(self, prompt: str, output_format: type):
        self.calls += 1
        for needle, (contradicts, reason) in self.verdicts.items():
            if needle in prompt:
                return output_format(contradicts=contradicts, reason=reason)
        return output_format(contradicts=False, reason="")


class TestProviderContradictionJudge:
    def test_returns_reason_when_contradicts(self) -> None:
        from ydk.core.contradiction_detector import ProviderContradictionJudge

        judge = ProviderContradictionJudge(_FakeStructured({"PostgreSQL": (True, "db changed")}))
        assert judge.judge_contradiction("Use SQLite", "Use PostgreSQL") == "db changed"

    def test_returns_none_when_no_contradiction(self) -> None:
        from ydk.core.contradiction_detector import ProviderContradictionJudge

        judge = ProviderContradictionJudge(_FakeStructured({}))
        assert judge.judge_contradiction("a", "b") is None

    def test_caches_repeated_pairs(self) -> None:
        from ydk.core.contradiction_detector import ProviderContradictionJudge

        fake = _FakeStructured({})
        judge = ProviderContradictionJudge(fake)
        judge.judge_contradiction("a", "b")
        judge.judge_contradiction("a", "b")
        assert fake.calls == 1

    def test_collects_handoffs_and_flushes_once(self, tmp_path) -> None:
        from ydk.core.contradiction_detector import ProviderContradictionJudge
        from ydk.core.llm_provider import SubagentHandoff, SubagentProvider

        provider = SubagentProvider(tmp_path, purpose="contradiction", model_tier="fast", model="m", agent="a")
        judge = ProviderContradictionJudge(provider)
        assert judge.judge_contradiction("new1", "old1") is None
        assert judge.judge_contradiction("new2", "old2") is None
        with pytest.raises(SubagentHandoff) as exc:
            judge.flush()
        assert len(exc.value.request_paths) == 2
        judge.flush()  # cleared: no-op

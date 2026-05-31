"""Tests for procedural memory — outcome tracking and improvement suggestions."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from odk.core.procedural_memory import ProceduralMemory
from odk.models.procedural import ProceduralReport


class FakeLLM:
    """Fake LLM for testing improvement suggestions."""

    def __init__(self, response: str = "Try being more specific") -> None:
        self._response = response
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self._response


@pytest.fixture
def proc_dir(tmp_path: Path) -> Path:
    d = tmp_path / "procedures"
    d.mkdir()
    return d


class TestRecordOutcome:
    def test_records_to_file(self, proc_dir: Path) -> None:
        proc = ProceduralMemory(storage_dir=proc_dir)
        proc.record_outcome("extract-v1", "abc123", success=True)
        path = proc_dir / "extract-v1.jsonl"
        assert path.exists()
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 1
        assert '"success":true' in lines[0]

    def test_multiple_outcomes_appended(self, proc_dir: Path) -> None:
        proc = ProceduralMemory(storage_dir=proc_dir)
        proc.record_outcome("extract-v1", "a", success=True)
        proc.record_outcome("extract-v1", "b", success=False, feedback="missed key detail")
        proc.record_outcome("extract-v1", "c", success=True)
        path = proc_dir / "extract-v1.jsonl"
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 3


class TestGetEffectiveness:
    def test_all_successes(self, proc_dir: Path) -> None:
        proc = ProceduralMemory(storage_dir=proc_dir)
        proc.record_outcome("p1", "a", success=True)
        proc.record_outcome("p1", "b", success=True)
        assert proc.get_effectiveness("p1") == 1.0

    def test_mixed(self, proc_dir: Path) -> None:
        proc = ProceduralMemory(storage_dir=proc_dir)
        proc.record_outcome("p1", "a", success=True)
        proc.record_outcome("p1", "b", success=False)
        assert proc.get_effectiveness("p1") == 0.5

    def test_no_outcomes_returns_zero(self, proc_dir: Path) -> None:
        proc = ProceduralMemory(storage_dir=proc_dir)
        assert proc.get_effectiveness("nonexistent") == 0.0


class TestSuggestImprovement:
    def test_suggests_when_below_threshold(self, proc_dir: Path) -> None:
        llm = FakeLLM(response="Add more context to the extraction prompt")
        proc = ProceduralMemory(storage_dir=proc_dir, llm=llm, threshold=0.8)
        proc.record_outcome("p1", "a", success=False, feedback="missed entities")
        proc.record_outcome("p1", "b", success=False, feedback="wrong format")
        proc.record_outcome("p1", "c", success=True)
        suggestion = proc.suggest_improvement("p1")
        assert suggestion == "Add more context to the extraction prompt"
        assert len(llm.calls) == 1

    def test_no_suggestion_when_above_threshold(self, proc_dir: Path) -> None:
        llm = FakeLLM()
        proc = ProceduralMemory(storage_dir=proc_dir, llm=llm, threshold=0.5)
        proc.record_outcome("p1", "a", success=True)
        proc.record_outcome("p1", "b", success=True)
        suggestion = proc.suggest_improvement("p1")
        assert suggestion is None
        assert len(llm.calls) == 0

    def test_graceful_without_llm(self, proc_dir: Path) -> None:
        proc = ProceduralMemory(storage_dir=proc_dir, llm=None, threshold=0.8)
        proc.record_outcome("p1", "a", success=False, feedback="bad")
        suggestion = proc.suggest_improvement("p1")
        assert suggestion is None

    def test_no_suggestion_for_empty_prompt(self, proc_dir: Path) -> None:
        llm = FakeLLM()
        proc = ProceduralMemory(storage_dir=proc_dir, llm=llm)
        suggestion = proc.suggest_improvement("nonexistent")
        assert suggestion is None


class TestGetReport:
    def test_report_structure(self, proc_dir: Path) -> None:
        proc = ProceduralMemory(storage_dir=proc_dir)
        proc.record_outcome("p1", "a", success=True)
        proc.record_outcome("p1", "b", success=False)
        proc.record_outcome("p1", "c", success=True)
        report = proc.get_report("p1")
        assert isinstance(report, ProceduralReport)
        assert report.prompt_id == "p1"
        assert report.total_executions == 3
        assert report.successes == 2
        assert report.failures == 1
        assert report.effectiveness == pytest.approx(2 / 3)


class TestListPromptIds:
    def test_lists_tracked_prompts(self, proc_dir: Path) -> None:
        proc = ProceduralMemory(storage_dir=proc_dir)
        proc.record_outcome("alpha", "a", success=True)
        proc.record_outcome("beta", "b", success=False)
        ids = proc.list_prompt_ids()
        assert ids == ["alpha", "beta"]

    def test_empty_dir(self, proc_dir: Path) -> None:
        proc = ProceduralMemory(storage_dir=proc_dir)
        assert proc.list_prompt_ids() == []

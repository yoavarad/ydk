"""Procedural memory — prompt outcome tracking and self-improvement suggestions."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Protocol

from ydk.models.procedural import ProceduralReport, PromptOutcome


class LLMProvider(Protocol):
    """LLM interface for improvement suggestions (mocked at system boundary)."""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Single completion."""
        ...


class ProceduralMemory:
    """Tracks extraction quality per prompt and suggests improvements."""

    DEFAULT_THRESHOLD = 0.7

    def __init__(
        self,
        storage_dir: str | Path = ".ydk/memory/procedures",
        llm: LLMProvider | None = None,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._llm = llm
        self._threshold = threshold

    def _outcomes_path(self, prompt_id: str) -> Path:
        """Path to the outcomes file for a given prompt."""
        return self._storage_dir / f"{prompt_id}.jsonl"

    def _load_outcomes(self, prompt_id: str) -> list[PromptOutcome]:
        """Load all outcomes for a prompt from disk."""
        path = self._outcomes_path(prompt_id)
        if not path.exists():
            return []
        return [
            PromptOutcome.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").strip().splitlines()
            if line.strip()
        ]

    def record_outcome(
        self,
        prompt_id: str,
        input_hash: str,
        success: bool,
        feedback: str | None = None,
    ) -> None:
        """Track extraction quality for a prompt execution."""
        outcome = PromptOutcome(
            prompt_id=prompt_id,
            input_hash=input_hash,
            success=success,
            feedback=feedback,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        path = self._outcomes_path(prompt_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(outcome.model_dump_json() + "\n")

    def get_effectiveness(self, prompt_id: str) -> float:
        """Success rate for a prompt. Returns 0.0 if no outcomes recorded."""
        outcomes = self._load_outcomes(prompt_id)
        if not outcomes:
            return 0.0
        return sum(1 for o in outcomes if o.success) / len(outcomes)

    def suggest_improvement(self, prompt_id: str) -> str | None:
        """If success rate < threshold, use LLM to suggest prompt improvement."""
        effectiveness = self.get_effectiveness(prompt_id)
        if effectiveness >= self._threshold:
            return None
        outcomes = self._load_outcomes(prompt_id)
        if not outcomes:
            return None
        if self._llm is None:
            return None
        failures = [o for o in outcomes if not o.success and o.feedback]
        feedback_lines = "\n".join(f"- {o.feedback}" for o in failures[:10])
        system_prompt = (
            "You are a prompt engineering expert. Given a prompt ID and failure feedback, "
            "suggest a concrete improvement to the prompt to increase its success rate. "
            "Be specific and actionable. Respond with only the suggestion text."
        )
        user_prompt = (
            f"Prompt ID: {prompt_id}\n"
            f"Success rate: {effectiveness:.0%}\n"
            f"Recent failure feedback:\n{feedback_lines}\n\n"
            "Suggest an improvement."
        )
        return self._llm.complete(system_prompt, user_prompt)

    def get_report(self, prompt_id: str) -> ProceduralReport:
        """Generate a report for a specific prompt."""
        outcomes = self._load_outcomes(prompt_id)
        total = len(outcomes)
        successes = sum(1 for o in outcomes if o.success)
        failures = total - successes
        effectiveness = successes / total if total > 0 else 0.0
        suggestion = self.suggest_improvement(prompt_id)
        return ProceduralReport(
            prompt_id=prompt_id,
            total_executions=total,
            successes=successes,
            failures=failures,
            effectiveness=effectiveness,
            suggestion=suggestion,
        )

    def list_prompt_ids(self) -> list[str]:
        """List all tracked prompt IDs."""
        return sorted(p.stem for p in self._storage_dir.glob("*.jsonl"))

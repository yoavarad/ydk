"""LLM-scored task complexity analysis (1-10)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from odk.models.complexity import ComplexityScore

if TYPE_CHECKING:
    from odk.models.pm import TaskDetail


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers used by the complexity scorer."""

    def invoke(self, prompt: str) -> str:
        """Send a prompt to an LLM and return the text response."""
        ...


_UNSCORED = 5
_UNSCORED_REASONING = "No LLM provider configured — returning default score."


def _build_prompt(task: TaskDetail, context: str | None = None) -> str:
    """Build the LLM prompt for complexity scoring."""
    lines = [
        "You are a task complexity analyst for a software project.",
        "",
        "Rate the following task on a 1-10 complexity scale:",
        "  1-3: Simple — single file change, clear path, no ambiguity",
        "  4-6: Moderate — multiple files, some design decisions, moderate risk",
        "  7-10: Complex — cross-cutting, high ambiguity, should be split",
        "",
        f"Title: {task.title}",
        f"Description: {task.description}",
    ]

    if task.acceptance_criteria:
        lines.append("Acceptance criteria:")
        for ac in task.acceptance_criteria:
            text = ac.text if hasattr(ac, "text") else str(ac)
            lines.append(f"  - {text}")

    if task.dependencies:
        lines.append(f"Dependencies: {', '.join(str(d) for d in task.dependencies)}")

    if task.spec_refs:
        lines.append(f"Spec references: {', '.join(task.spec_refs)}")

    if context:
        lines.append(f"\nAdditional context: {context}")

    lines.extend(
        [
            "",
            "Return JSON only:",
            "{",
            '  "score": <1-10>,',
            '  "reasoning": "<1-2 sentence explanation>",',
            '  "should_expand": <true if score >= 8>,',
            '  "suggested_splits": ["<subtask 1>", "<subtask 2>"] or []',
            "}",
        ]
    )
    return "\n".join(lines)


def _parse_response(task_id: str, response: str) -> ComplexityScore:
    """Parse LLM JSON response into a ComplexityScore."""
    text = response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    data = json.loads(text)
    score = int(data["score"])
    score = max(1, min(10, score))

    return ComplexityScore(
        task_id=task_id,
        score=score,
        reasoning=data.get("reasoning", ""),
        should_expand=data.get("should_expand", score >= 8),
        suggested_splits=data.get("suggested_splits", []),
    )


class ComplexityScorer:
    """LLM-based task complexity scorer.

    Uses an LLM provider to analyze tasks and return a 1-10 complexity
    score with reasoning and expansion recommendations.
    """

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self._llm = llm_provider

    def score_task(
        self,
        task: TaskDetail,
        context: str | None = None,
    ) -> ComplexityScore:
        """Score a single task's complexity.

        Returns a default score of 5 when no LLM provider is configured.
        """
        task_id = task.id or f"#{task.number}"

        if self._llm is None:
            return ComplexityScore(
                task_id=task_id,
                score=_UNSCORED,
                reasoning=_UNSCORED_REASONING,
                should_expand=False,
                suggested_splits=[],
            )

        prompt = _build_prompt(task, context)
        response = self._llm.invoke(prompt)

        try:
            return _parse_response(task_id, response)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return ComplexityScore(
                task_id=task_id,
                score=_UNSCORED,
                reasoning=f"LLM response could not be parsed: {response[:120]}",
                should_expand=False,
                suggested_splits=[],
            )

    def score_tasks(
        self,
        tasks: list[TaskDetail],
        context: str | None = None,
    ) -> list[ComplexityScore]:
        """Score multiple tasks sequentially."""
        return [self.score_task(t, context) for t in tasks]

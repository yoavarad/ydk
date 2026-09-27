"""LLM-scored task complexity analysis (1-10)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from ydk.models.complexity import ComplexityScore

if TYPE_CHECKING:
    from ydk.core.llm_provider import StructuredLLMProvider
    from ydk.models.pm import TaskDetail


_UNSCORED = 5
_UNSCORED_REASONING = "No LLM provider configured — returning default score."


class ComplexityAssessment(BaseModel):
    """Structured output the LLM returns for one task."""

    score: int
    reasoning: str
    should_expand: bool
    suggested_splits: list[str]


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
            "Respond with:",
            "  score: 1-10",
            "  reasoning: 1-2 sentence explanation",
            "  should_expand: true if score >= 8",
            "  suggested_splits: list of subtask titles, or an empty list",
        ]
    )
    return "\n".join(lines)


def _to_score(task_id: str, assessment: ComplexityAssessment) -> ComplexityScore:
    """Convert the LLM assessment into a ComplexityScore, clamping the score to 1-10."""
    return ComplexityScore(
        task_id=task_id,
        score=max(1, min(10, assessment.score)),
        reasoning=assessment.reasoning,
        should_expand=assessment.should_expand,
        suggested_splits=assessment.suggested_splits,
    )


class ComplexityScorer:
    """LLM-based task complexity scorer.

    Uses an LLM provider to analyze tasks and return a 1-10 complexity
    score with reasoning and expansion recommendations.
    """

    def __init__(self, llm_provider: StructuredLLMProvider | None = None) -> None:
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
        return _to_score(task_id, self._llm.invoke_structured(prompt, ComplexityAssessment))

    def score_tasks(
        self,
        tasks: list[TaskDetail],
        context: str | None = None,
    ) -> list[ComplexityScore]:
        """Score multiple tasks sequentially."""
        return [self.score_task(t, context) for t in tasks]

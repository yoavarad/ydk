"""Task compaction -- summarize completed tasks to reduce context burden."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ydk.models.compaction import CompactedTask

if TYPE_CHECKING:
    from ydk.core.llm_provider import LLMProvider
    from ydk.models.pm import TaskDetail


_COMPACTABLE_STATUSES = frozenset({"done", "closed"})


def _build_compaction_prompt(task: TaskDetail) -> str:
    """Build the LLM prompt for task compaction."""
    lines = [
        "You are a task summarizer for a software project.",
        "",
        "Summarize the following completed task. Preserve key decisions",
        "and files modified, but discard verbose implementation detail.",
        "",
        f"Task ID: {task.id}",
        f"Title: {task.title}",
        f"Status: {task.status}",
        f"Description: {task.description}",
        "",
        "Return JSON only:",
        "{",
        '  "summary": "<1-3 sentence summary of what was accomplished>",',
        '  "key_decisions": ["<decision 1>", "<decision 2>"],',
        '  "files_modified": ["<file 1>", "<file 2>"]',
        "}",
    ]
    return "\n".join(lines)


def _deterministic_compact(task: TaskDetail) -> CompactedTask:
    """Fallback compaction without LLM -- deterministic truncation."""
    summary = f"Completed: {task.title}."
    if task.description:
        first_sentence = task.description.split(".")[0].strip()
        if first_sentence:
            summary = f"{summary} {first_sentence}."

    return CompactedTask(
        id=task.id,
        title=task.title,
        status=task.status,
        summary=summary,
        key_decisions=[],
        files_modified=[],
        original_description=task.description,
        compacted_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def _parse_llm_response(
    task: TaskDetail,
    response: str,
) -> CompactedTask | None:
    """Parse LLM JSON response into a CompactedTask, or None on failure."""
    try:
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        data = json.loads(text)
        return CompactedTask(
            id=task.id,
            title=task.title,
            status=task.status,
            summary=data.get("summary", ""),
            key_decisions=data.get("key_decisions", []),
            files_modified=data.get("files_modified", []),
            original_description=task.description,
            compacted_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


class TaskCompactor:
    """Compact completed tasks into context-efficient summaries.

    Uses LLMProvider for intelligent summarization when available.
    Falls back to deterministic truncation otherwise.
    """

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self._llm = llm_provider

    def is_compactable(self, task: TaskDetail) -> bool:
        """Return True if the task can be compacted (done or closed)."""
        return task.status in _COMPACTABLE_STATUSES

    def compact_task(self, task: TaskDetail) -> CompactedTask:
        """Compact a single completed task.

        Raises ValueError if the task is not in a compactable state.
        """
        if not self.is_compactable(task):
            msg = f"Task {task.id} is not compactable (status={task.status!r}, must be done or closed)"
            raise ValueError(msg)

        if self._llm is not None:
            prompt = _build_compaction_prompt(task)
            response = self._llm.invoke(prompt)
            result = _parse_llm_response(task, response)
            if result is not None:
                return result

        return _deterministic_compact(task)

    def compact_tasks(
        self,
        tasks: list[TaskDetail],
    ) -> list[CompactedTask]:
        """Compact multiple tasks sequentially."""
        return [self.compact_task(t) for t in tasks]

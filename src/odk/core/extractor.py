"""LLM-based memory extraction from development session transcripts.

Uses Strands Agents with Amazon Bedrock to send a transcript to an LLM
and parse structured memory entries from the response.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

EXTRACTION_PROMPT = """\
You are a memory extraction agent observing a completed development session transcript.

Your job is to identify facts, decisions, and discoveries that would be valuable
for a developer returning to this codebase in a future session. Each extracted
memory must be **self-contained** -- understandable without the original transcript.

## What to extract

- **discovery**: Something learned about how the system works, an unexpected behavior,
  or a finding from investigation. Use verbs like "discovered", "found", "confirmed".
- **decision**: An architectural or design choice with rationale -- why X was chosen
  over Y. Use verbs like "decided", "chose", "opted for".
- **gotcha**: A trap, edge case, or surprising behavior that would trip up someone
  unfamiliar. Use verbs like "beware", "note that", "surprisingly".
- **pattern**: A reusable approach, convention, or technique established during the
  session. Use verbs like "established", "adopted", "standardized".
- **convention**: A naming, structural, or workflow convention agreed upon or
  discovered. Use verbs like "convention is", "always use", "named as".
- **abandoned**: An approach that was tried and explicitly rejected, with the
  reason for rejection. These are the highest-value memories -- they prevent
  repeating failures. Use verbs like "tried and rejected", "abandoned",
  "ruled out". Include what was tried and why it was rejected.

## What to skip

- Routine file reads with no surprising findings
- Standard test runs that passed without incident
- Package installations and dependency updates
- Git operations (commit, push, branch)
- Repetitive operations already documented in another memory

If nothing is worth extracting, return an empty JSON array `[]`.

## Concept tags (pick all that apply to each memory)

- `how-it-works` -- understanding mechanisms
- `why-it-exists` -- purpose or rationale
- `what-changed` -- modifications made
- `problem-solution` -- issues and their fixes
- `gotcha` -- traps or edge cases
- `pattern` -- reusable approach
- `trade-off` -- pros/cons of a decision

## Related files

For each memory, list any file paths mentioned in the conversation that are
relevant. Use paths as they appear in the transcript (relative or absolute).

## Importance

- **high** -- affects architecture, cross-cutting concerns, or would cause significant
  rework if forgotten
- **medium** -- useful pattern or finding that saves time
- **low** -- nice to know, minor detail

## Output format

Return a JSON array of objects. Each object has these fields:

```json
[
  {
    "memory_type": "discovery | decision | gotcha | pattern | convention | abandoned",
    "content": "Self-contained description. No pronouns. Include file names, function names, concrete values.",
    "related_files": ["path/to/file.py"],
    "concepts": ["how-it-works", "gotcha"],
    "importance": "high | medium | low"
  }
]
```

Rules for writing `content`:
1. Each statement must stand alone -- no "it", "this", "the above"
2. Include specific file names, function names, class names, config keys
3. State the fact, not the process of discovering it ("X uses Y" not "we found that X uses Y")
4. Maximum 3 sentences per memory
5. Prefer concrete over abstract

Return ONLY the JSON array, no commentary before or after.
"""


@dataclass
class ExtractedMemory:
    """A single memory extracted from a development session."""

    memory_type: str  # discovery, decision, gotcha, pattern, convention
    content: str
    related_files: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    importance: str = "medium"


class MemoryExtractor:
    """Extract structured memories from conversation transcripts using an LLM.

    Requires the ``strands-agents`` package (install via ``uv pip install odk[ai]``).
    Uses Amazon Bedrock as the model provider.
    """

    def __init__(
        self,
        aws_profile: str = "",
        model: str = "us.anthropic.claude-sonnet-4-6",
    ) -> None:
        self._aws_profile = aws_profile
        self._model = model

    def extract_from_transcript(
        self,
        conversation: str,
        task_context: str = "",
    ) -> list[ExtractedMemory]:
        """Send a conversation transcript to an LLM and extract structured memories.

        Parameters
        ----------
        conversation:
            The conversation text (e.g. output of ``format_as_conversation``).
        task_context:
            Optional additional context about the task being performed.

        Returns
        -------
        list[ExtractedMemory]
            Extracted memories parsed from the LLM response.
        """
        if not conversation.strip():
            return []

        agent = self._build_agent()

        user_message = self._build_user_message(conversation, task_context)
        result = agent(user_message)

        return self._parse_response(str(result))

    def extract_from_jsonl(
        self,
        jsonl_path: Path,
        task_context: str = "",
    ) -> list[ExtractedMemory]:
        """Parse a JSONL transcript file and extract memories.

        Convenience method that combines transcript parsing with extraction.
        """
        from odk.core.transcript_parser import format_as_conversation, parse_transcript

        messages = parse_transcript(jsonl_path)
        conversation = format_as_conversation(messages)
        return self.extract_from_transcript(conversation, task_context)

    def _build_agent(self) -> Callable[..., Any]:
        """Create a Strands Agent configured for memory extraction."""
        try:
            from strands import Agent
            from strands.models.bedrock import BedrockModel
        except ImportError:
            raise ImportError("Memory extraction requires strands-agents: uv pip install odk[ai]") from None

        import boto3

        session = boto3.Session(
            profile_name=self._aws_profile if self._aws_profile else None,
        )
        model = BedrockModel(
            model_id=self._model,
            boto_session=session,
        )
        return Agent(
            model=model,
            system_prompt=EXTRACTION_PROMPT,
            tools=[],
        )

    @staticmethod
    def _build_user_message(conversation: str, task_context: str) -> str:
        """Build the user message sent to the extraction agent."""
        parts: list[str] = []
        if task_context:
            parts.append(f"Task context: {task_context}\n")
        parts.append("Here is the development session transcript:\n")
        parts.append(conversation)
        return "\n".join(parts)

    @staticmethod
    def _parse_response(response_text: str) -> list[ExtractedMemory]:
        """Parse the LLM JSON response into ExtractedMemory dataclasses."""
        # The LLM should return a JSON array, but may wrap it in markdown fences.
        text = response_text.strip()

        # Strip markdown code fences if present.
        if text.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = text.index("\n")
            text = text[first_newline + 1 :]
            # Remove closing fence
            if text.endswith("```"):
                text = text[: -len("```")].rstrip()

        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            # Try to find a JSON array in the response.
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1 and end > start:
                try:
                    raw = json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    return []
            else:
                return []

        if not isinstance(raw, list):
            return []

        memories: list[ExtractedMemory] = []
        valid_types = {"discovery", "decision", "gotcha", "pattern", "convention", "abandoned"}
        valid_importance = {"high", "medium", "low"}

        for item in raw:
            if not isinstance(item, dict):
                continue

            memory_type = str(item.get("memory_type", "")).strip()
            content = str(item.get("content", "")).strip()

            if not content:
                continue
            if memory_type not in valid_types:
                memory_type = "discovery"  # default fallback

            importance = str(item.get("importance", "medium")).strip()
            if importance not in valid_importance:
                importance = "medium"

            related_files = item.get("related_files", [])
            if not isinstance(related_files, list):
                related_files = []
            related_files = [str(f) for f in related_files if f]

            concepts = item.get("concepts", [])
            if not isinstance(concepts, list):
                concepts = []
            concepts = [str(c) for c in concepts if c]

            memories.append(
                ExtractedMemory(
                    memory_type=memory_type,
                    content=content,
                    related_files=related_files,
                    concepts=concepts,
                    importance=importance,
                )
            )

        return memories

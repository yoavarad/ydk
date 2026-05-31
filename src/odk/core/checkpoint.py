"""Checkpoint review guide generator — structured human review for git diffs."""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from odk.models.checkpoint import BlastRadiusSpot, CheckpointPreview, ReviewConcern

if TYPE_CHECKING:
    from odk.models.pm import TaskDetail


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers used by the checkpoint generator."""

    def invoke(self, prompt: str) -> str:
        """Send a prompt to an LLM and return the text response."""
        ...


def _parse_diff_stats(diff: str) -> tuple[list[str], int, int]:
    """Extract files changed, insertions, and deletions from a unified diff."""
    files: list[str] = []
    insertions = 0
    deletions = 0
    for line in diff.splitlines():
        if line.startswith("+++ b/") or line.startswith("--- a/"):
            fname = line[6:]
            if fname not in files:
                files.append(fname)
        elif line.startswith("+") and not line.startswith("+++"):
            insertions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return files, insertions, deletions


def _group_by_directory(files: list[str]) -> dict[str, list[str]]:
    """Group files by their top-level directory as a fallback grouping strategy."""
    groups: dict[str, list[str]] = {}
    for f in files:
        parts = PurePosixPath(f).parts
        key = parts[0] if len(parts) > 1 else "root"
        groups.setdefault(key, []).append(f)
    return groups


def _build_llm_prompt(diff: str, task_title: str | None) -> str:
    """Build the LLM prompt for intelligent concern grouping."""
    task_context = f"Task: {task_title}\n" if task_title else ""
    lines = [
        "You are a code review assistant. Analyze the following git diff and produce",
        "a structured review guide.",
        "",
        task_context,
        "Group the changes by CONCERN (what they affect), not by file.",
        "Identify the 2-5 highest blast-radius spots.",
        "Suggest testing approaches.",
        "",
        "Return JSON:",
        "{",
        '  "intent": "one-line description of what this diff does",',
        '  "concerns": [',
        '    {"concern": "name", "files": ["file1.py"], "summary": "what changed"}',
        "  ],",
        '  "blast_radius": [',
        '    {"location": "file:line", "risk": "why", "suggestion": "what to check"}',
        "  ],",
        '  "testing_suggestions": ["suggestion1", "suggestion2"]',
        "}",
        "",
        "--- DIFF ---",
        diff[:8000],
    ]
    return "\n".join(lines)


def _parse_llm_response(response: str, files: list[str], insertions: int, deletions: int) -> CheckpointPreview:
    """Parse LLM JSON response into a CheckpointPreview."""
    text = response.strip()
    # Strip code fences
    if text.startswith("```"):
        fence_lines = text.split("\n")
        fence_lines = fence_lines[1:]
        if fence_lines and fence_lines[-1].strip() == "```":
            fence_lines = fence_lines[:-1]
        text = "\n".join(fence_lines)

    data = json.loads(text)

    concerns = [
        ReviewConcern(
            concern=c.get("concern", ""),
            files=c.get("files", []),
            summary=c.get("summary", ""),
        )
        for c in data.get("concerns", [])
    ]

    blast_radius = [
        BlastRadiusSpot(
            location=b.get("location", ""),
            risk=b.get("risk", ""),
            suggestion=b.get("suggestion", ""),
        )
        for b in data.get("blast_radius", [])
    ]

    return CheckpointPreview(
        intent=data.get("intent", ""),
        files_changed=len(files),
        insertions=insertions,
        deletions=deletions,
        concerns=concerns,
        blast_radius=blast_radius,
        testing_suggestions=data.get("testing_suggestions", []),
    )


class CheckpointGenerator:
    """Generate structured review guides from git diffs.

    Uses an LLM for intelligent grouping when available;
    falls back to directory-based grouping otherwise.
    """

    def generate(
        self,
        diff: str,
        task: TaskDetail | None = None,
        llm_provider: LLMProvider | None = None,
    ) -> CheckpointPreview:
        """Analyze a git diff and produce a structured review guide.

        If no LLM provider is given, falls back to grouping by directory.
        """
        files, insertions, deletions = _parse_diff_stats(diff)

        if not files:
            return CheckpointPreview(
                intent="Empty diff — no changes detected.",
                files_changed=0,
                insertions=0,
                deletions=0,
            )

        task_title = task.title if task else None

        if llm_provider is not None:
            try:
                prompt = _build_llm_prompt(diff, task_title)
                response = llm_provider.invoke(prompt)
                return _parse_llm_response(response, files, insertions, deletions)
            except (json.JSONDecodeError, KeyError, TypeError):
                pass  # Fall through to directory-based grouping

        # Fallback: group by directory
        return self._fallback_generate(files, insertions, deletions, task_title)

    def _fallback_generate(
        self,
        files: list[str],
        insertions: int,
        deletions: int,
        task_title: str | None,
    ) -> CheckpointPreview:
        """Directory-based fallback when no LLM is available."""
        groups = _group_by_directory(files)

        concerns = [
            ReviewConcern(
                concern=directory,
                files=group_files,
                summary=f"{len(group_files)} file(s) changed in {directory}/",
            )
            for directory, group_files in sorted(groups.items())
        ]

        intent = task_title or f"Changes across {len(files)} file(s)"

        # Identify potential blast-radius spots heuristically
        blast_radius: list[BlastRadiusSpot] = []
        for f in files:
            name = PurePosixPath(f).name
            if re.search(r"(__init__|config|schema|migration)", name):
                blast_radius.append(
                    BlastRadiusSpot(
                        location=f,
                        risk=f"Infrastructure file ({name}) — changes may cascade",
                        suggestion="Verify imports and downstream consumers",
                    )
                )
            if len(blast_radius) >= 5:
                break

        testing_suggestions = ["Run the full test suite", "Check for import errors"]

        return CheckpointPreview(
            intent=intent,
            files_changed=len(files),
            insertions=insertions,
            deletions=deletions,
            concerns=concerns,
            blast_radius=blast_radius,
            testing_suggestions=testing_suggestions,
        )

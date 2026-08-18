"""Parse Claude Code JSONL session transcripts into structured messages.

Claude Code stores full session transcripts as JSONL files at:
  ~/.claude/projects/<project-hash>/<session-uuid>.jsonl

Each line is a JSON object with a 'type' field. This module extracts
user/assistant text messages, strips system reminders and tool results,
and returns clean (role, text) pairs suitable for LLM consumption.

Adapted from parse_session.py (claude-code-utils).
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

ANSI_ESCAPE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences."""
    return ANSI_ESCAPE.sub("", text)


def _strip_system_reminders(text: str) -> str:
    """Remove <system-reminder>...</system-reminder> blocks."""
    return SYSTEM_REMINDER.sub("", text).strip()


def parse_transcript(jsonl_path: Path) -> list[tuple[str, str]]:
    """Parse a Claude Code JSONL transcript into (role, text) message pairs.

    Reads each line of the JSONL file. Keeps only ``user`` and ``assistant``
    message types. For each message:

    - Extracts text blocks (skips tool_use, tool_result, thinking blocks)
    - Strips ANSI escape codes and system reminders
    - Skips user messages that contain only tool results (no real text)
    - Skips messages with no remaining text after filtering

    Returns a list of ``(role, text)`` tuples where *role* is ``"user"``
    or ``"assistant"`` and *text* is the cleaned message content.

    Raises no exceptions on missing/empty files -- returns an empty list.
    """
    if not jsonl_path.exists():
        return []

    messages: list[tuple[str, str]] = []

    with jsonl_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if obj.get("type") not in ("user", "assistant"):
                continue

            inner = obj.get("message", {})
            role: str = inner.get("role", obj["type"])
            content = inner.get("content", "")

            texts: list[str] = []
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                # For user messages, check whether there is any real text
                # (i.e. not just tool_result blocks and system reminders).
                if role == "user" and not _has_real_user_text(content):
                    continue

                for block in content:
                    if isinstance(block, str):
                        texts.append(block)
                    elif isinstance(block, dict) and block.get("type") == "text":
                        t = block.get("text", "")
                        if t.strip():
                            texts.append(t)

            combined = _strip_ansi("\n".join(texts)).strip()
            if not combined:
                continue

            combined = _strip_system_reminders(combined)
            if not combined:
                continue

            messages.append((role, combined))

    return messages


def _has_real_user_text(content: list[Any]) -> bool:
    """Return True if the content list has real text (not just tool results / system reminders)."""
    for block in content:
        if isinstance(block, dict):
            if block.get("type") != "text":
                continue
            t = str(block.get("text", "")).strip()
            if t and not t.startswith("<system-reminder>"):
                return True
        elif isinstance(block, str):
            t = block.strip()
            if t and not t.startswith("<system-reminder>"):
                return True
    return False


def format_as_conversation(messages: list[tuple[str, str]]) -> str:
    """Format (role, text) pairs as readable conversation text for LLM consumption.

    Output format::

        [User]
        Tell me about the auth module

        [Assistant]
        The auth module handles JWT tokens...

    """
    if not messages:
        return ""

    parts: list[str] = []
    for role, text in messages:
        label = "User" if role == "user" else "Assistant"
        parts.append(f"[{label}]\n{text}")
    return "\n\n".join(parts)

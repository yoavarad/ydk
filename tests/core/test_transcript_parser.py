"""Tests for ydk.core.transcript_parser — JSONL transcript parsing."""

from __future__ import annotations

import json
from pathlib import Path

from ydk.core.transcript_parser import format_as_conversation, parse_transcript

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_SESSION = FIXTURE_DIR / "sample_session.jsonl"


class TestParseTranscript:
    def test_parses_user_and_assistant_messages(self) -> None:
        messages = parse_transcript(SAMPLE_SESSION)
        roles = [role for role, _ in messages]
        assert "user" in roles
        assert "assistant" in roles

    def test_extracts_text_content(self) -> None:
        messages = parse_transcript(SAMPLE_SESSION)
        # First user message should be about JWT auth
        first_user = next(text for role, text in messages if role == "user")
        assert "JWT" in first_user

    def test_strips_system_reminders(self) -> None:
        messages = parse_transcript(SAMPLE_SESSION)
        for _, text in messages:
            assert "<system-reminder>" not in text

    def test_skips_tool_result_only_messages(self) -> None:
        """User messages containing only tool results (no real text) are skipped."""
        messages = parse_transcript(SAMPLE_SESSION)
        for _, text in messages:
            # No message should be just a tool result echo
            assert "File edited successfully." not in text

    def test_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        result = parse_transcript(tmp_path / "nonexistent.jsonl")
        assert result == []

    def test_returns_empty_for_empty_file(self, tmp_path: Path) -> None:
        empty_file = tmp_path / "empty.jsonl"
        empty_file.write_text("")
        result = parse_transcript(empty_file)
        assert result == []

    def test_skips_malformed_json_lines(self, tmp_path: Path) -> None:
        jsonl = tmp_path / "bad.jsonl"
        lines = [
            "not json at all",
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": "hello",
                    },
                }
            ),
            "{invalid json",
        ]
        jsonl.write_text("\n".join(lines))
        messages = parse_transcript(jsonl)
        assert len(messages) == 1
        assert messages[0] == ("user", "hello")

    def test_skips_non_user_assistant_types(self, tmp_path: Path) -> None:
        jsonl = tmp_path / "system_only.jsonl"
        line = json.dumps(
            {
                "type": "system",
                "message": {"role": "system", "content": "You are Claude."},
            }
        )
        jsonl.write_text(line + "\n")
        assert parse_transcript(jsonl) == []

    def test_multiple_messages_preserves_order(self) -> None:
        messages = parse_transcript(SAMPLE_SESSION)
        assert len(messages) >= 4
        # First message is from user, second from assistant
        assert messages[0][0] == "user"
        assert messages[1][0] == "assistant"


class TestFormatAsConversation:
    def test_formats_basic_pairs(self) -> None:
        messages = [("user", "hello"), ("assistant", "hi there")]
        result = format_as_conversation(messages)
        assert "[User]" in result
        assert "[Assistant]" in result
        assert "hello" in result
        assert "hi there" in result

    def test_empty_messages_returns_empty_string(self) -> None:
        assert format_as_conversation([]) == ""

    def test_messages_separated_by_blank_lines(self) -> None:
        messages = [("user", "one"), ("assistant", "two")]
        result = format_as_conversation(messages)
        parts = result.split("\n\n")
        assert len(parts) == 2

    def test_roundtrip_with_parse(self) -> None:
        """parse_transcript -> format_as_conversation produces readable output."""
        messages = parse_transcript(SAMPLE_SESSION)
        conversation = format_as_conversation(messages)
        assert len(conversation) > 100
        assert "[User]" in conversation
        assert "[Assistant]" in conversation

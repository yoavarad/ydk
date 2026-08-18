"""Tests for commit-msg hook validation."""

from __future__ import annotations

from ydk.hooks.commit_msg import validate_commit_message

VALID_TYPES = [
    "feat",
    "fix",
    "docs",
    "chore",
    "refactor",
    "test",
    "ci",
    "perf",
    "release",
    "bump",
]


class TestValidMessages:
    """Valid conventional-commit messages must pass."""

    def test_type_and_description(self) -> None:
        assert validate_commit_message("feat: add login page") is True

    def test_type_scope_description(self) -> None:
        assert validate_commit_message("fix(auth): resolve token expiry") is True

    def test_all_types_accepted(self) -> None:
        for typ in VALID_TYPES:
            assert validate_commit_message(f"{typ}: some change") is True, f"type '{typ}' should be valid"

    def test_scope_with_hyphen(self) -> None:
        assert validate_commit_message("feat(my-scope): something") is True

    def test_scope_with_underscore(self) -> None:
        assert validate_commit_message("feat(my_scope): something") is True

    def test_multi_line_body(self) -> None:
        msg = "feat: add login\n\nThis adds the login page.\n\nSigned-off-by: Dev"
        assert validate_commit_message(msg) is True

    def test_bump_prefix_allowed(self) -> None:
        assert validate_commit_message("bump: 1.2.3") is True

    def test_description_with_special_chars(self) -> None:
        assert validate_commit_message("fix: handle `None` in parser — edge case") is True


class TestInvalidMessages:
    """Invalid messages must fail."""

    def test_missing_type(self) -> None:
        assert validate_commit_message("add login page") is False

    def test_unknown_type(self) -> None:
        assert validate_commit_message("feature: add login page") is False

    def test_missing_colon(self) -> None:
        assert validate_commit_message("feat add login page") is False

    def test_missing_space_after_colon(self) -> None:
        assert validate_commit_message("feat:add login page") is False

    def test_empty_description(self) -> None:
        assert validate_commit_message("feat: ") is False

    def test_empty_message(self) -> None:
        assert validate_commit_message("") is False

    def test_only_type(self) -> None:
        assert validate_commit_message("feat") is False

    def test_uppercase_type(self) -> None:
        assert validate_commit_message("FEAT: add login page") is False

    def test_empty_scope(self) -> None:
        assert validate_commit_message("feat(): add login page") is False

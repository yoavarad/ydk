"""Protocol definitions (interfaces) for ODK services.

Core logic depends on these protocols, not on concrete implementations.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

_T = TypeVar("_T")


class LLMProvider(Protocol):
    """Abstract LLM interaction. Bedrock is one implementation."""

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Single completion."""
        ...

    async def complete_structured(self, system_prompt: str, user_prompt: str, schema: type[_T]) -> _T:
        """Completion with structured output (JSON parsed into schema)."""
        ...


class GitService(Protocol):
    """Git operations."""

    def changed_files(self, directory: str, base_ref: str = "main", extension: str = ".md") -> list[str]:
        """Return files changed relative to base_ref."""
        ...

    def all_files(self, directory: str, extension: str = ".md") -> list[str]:
        """Return all files matching extension in directory."""
        ...

    def read_content(self, files: list[str]) -> str:
        """Concatenate files into a single string, each prefixed with path."""
        ...

    def current_branch(self) -> str:
        """Return the current git branch name."""
        ...


class RemoteService(Protocol):
    """GitHub/GitLab API operations."""

    def create_issue(self, title: str, body: str, labels: list[str], milestone: str | None = None) -> str:
        """Create an issue and return its URL."""
        ...

    def list_issues(
        self, milestone: str | None = None, labels: list[str] | None = None, state: str = "open"
    ) -> list[dict[str, str]]:
        """List issues filtered by milestone, labels, or state."""
        ...

    def add_label(self, issue_number: int, label: str) -> None:
        """Add a label to an issue."""
        ...

    def add_comment(self, issue_number: int, comment: str) -> None:
        """Append a comment to an issue."""
        ...

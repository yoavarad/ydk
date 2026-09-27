"""Provider-agnostic LLM seam.

YDK ships no concrete provider and makes no external LLM API calls (#231).
Reasoning runs in the in-session agent; core modules accept an optional
injected ``LLMProvider`` and fall back to deterministic behavior when absent.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers optionally injected into YDK's core modules."""

    def invoke(self, prompt: str) -> str:
        """Send a prompt to an LLM and return the text response."""
        ...

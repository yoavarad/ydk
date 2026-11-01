"""Shared CLI handling for subagent LLM handoffs (see ADR 0004)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

import typer

from ydk.core.llm_provider import SubagentHandoff

if TYPE_CHECKING:
    from collections.abc import Iterator

HANDOFF_EXIT_CODE = 3


@contextmanager
def handle_subagent_handoff() -> Iterator[None]:
    """Turn a ``SubagentHandoff`` into a machine-parseable request block and exit code 3."""
    try:
        yield
    except SubagentHandoff as handoff:
        typer.echo("YDK-SUBAGENT-REQUESTS:")
        for path in handoff.request_paths:
            typer.echo(f"- {path}")
        typer.echo("Rerun this command after writing responses.")
        raise typer.Exit(code=HANDOFF_EXIT_CODE) from None

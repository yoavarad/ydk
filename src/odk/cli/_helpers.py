"""Shared CLI helpers — eliminates duplication across command modules."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from collections.abc import Callable

from odk.output.formatters import OutputFormat, get_formatter


def get_output_format(ctx: typer.Context) -> OutputFormat:
    """Extract the output format from the Typer context object.

    Every CLI module was duplicating this 3-line helper as ``_get_format``.
    """
    obj = ctx.ensure_object(dict)
    return obj.get("format", OutputFormat.human)


def format_or_echo(
    ctx: typer.Context,
    data: object,
    *,
    human_fn: Callable[[], None] | None = None,
) -> bool:
    """If format is json/yaml, serialize *data* and echo it. Return True if handled.

    When the output format is ``human``, returns False so the caller can
    render its own Rich/plain output.  If *human_fn* is provided and callable,
    it is invoked for human format and True is returned.

    This collapses the repeated pattern::

        fmt = _get_format(ctx)
        if fmt in (OutputFormat.json, OutputFormat.yaml):
            formatter = get_formatter(fmt)
            typer.echo(formatter.format(data))
            return
    """
    fmt = get_output_format(ctx)
    if fmt in (OutputFormat.json, OutputFormat.yaml):
        formatter = get_formatter(fmt)
        typer.echo(formatter.format(data))  # ty: ignore[invalid-argument-type]  # formatters handle any type
        return True
    if callable(human_fn):
        human_fn()
        return True
    return False

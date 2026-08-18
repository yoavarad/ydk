"""Root Typer app with global flags."""

from __future__ import annotations

import importlib.metadata
import logging

import typer

from ydk.core.log_setup import set_console_level, setup_ydk_logger
from ydk.output.formatters import OutputFormat

app = typer.Typer(name="ydk", help="YDK — Yoav Development Kit", no_args_is_help=True)


def _version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        version = importlib.metadata.version("ydk")
        typer.echo(f"ydk {version}")
        raise typer.Exit()


@app.callback()
def main_callback(
    ctx: typer.Context,
    format: OutputFormat = typer.Option(OutputFormat.human, "--format", "-f", help="Output format"),  # noqa: B008
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    version: bool = typer.Option(None, "--version", callback=_version_callback, is_eager=True, help="Show version"),
) -> None:
    """YDK — Yoav Development Kit."""
    ctx.ensure_object(dict)
    ctx.obj["format"] = format
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet

    # Set up structured logging
    setup_ydk_logger()
    if verbose:
        set_console_level(logging.DEBUG)
    elif quiet:
        set_console_level(logging.ERROR)

"""Root Typer app with global flags."""

from __future__ import annotations

import importlib.metadata
import logging

import typer

from odk.core.log_setup import set_console_level, setup_odk_logger
from odk.output.formatters import OutputFormat

app = typer.Typer(name="odk", help="ODK — Oz Development Kit", no_args_is_help=True)


def _version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        version = importlib.metadata.version("odk")
        typer.echo(f"odk {version}")
        raise typer.Exit()


@app.callback()
def main_callback(
    ctx: typer.Context,
    format: OutputFormat = typer.Option(OutputFormat.human, "--format", "-f", help="Output format"),  # noqa: B008
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    version: bool = typer.Option(None, "--version", callback=_version_callback, is_eager=True, help="Show version"),
) -> None:
    """ODK — Oz Development Kit."""
    ctx.ensure_object(dict)
    ctx.obj["format"] = format
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet

    # Set up structured logging
    setup_odk_logger()
    if verbose:
        set_console_level(logging.DEBUG)
    elif quiet:
        set_console_level(logging.ERROR)

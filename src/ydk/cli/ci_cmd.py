"""ydk ci — generate GitHub Actions workflows for a YDK project."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from ydk.cli._helpers import format_or_echo
from ydk.core.ci_generator import CiConfigError, CiInitResult, generate_ci
from ydk.output.console import console

ci_app = typer.Typer(help="CI workflow generation", no_args_is_help=True)

FORCE_HINT = "Re-run with --force to overwrite skipped files."


def print_ci_summary(result: CiInitResult) -> None:
    """Print the unpublished-version warning, the per-file table and the skip hint."""
    if result.unpublished:
        console.print(
            f"[yellow]Warning: ydk {result.version} is not a release; the pinned v{result.version} tag may not exist.",
            soft_wrap=True,
        )
    table = Table(title="CI files")
    table.add_column("Path")
    table.add_column("Action")
    table.add_column("Purpose")
    for f in result.files:
        table.add_row(f.path, f.action, f.purpose)
    console.print(table)
    if result.skipped:
        console.print(FORCE_HINT)


@ci_app.command("init")
def init(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="Overwrite existing generated files"),
) -> None:
    """Generate .github/workflows/* and the PR template from the project config."""
    try:
        result = generate_ci(Path("."), force=force)
    except CiConfigError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None

    format_or_echo(
        ctx,
        {"written": result.written, "skipped": result.skipped},
        human_fn=lambda: print_ci_summary(result),
    )

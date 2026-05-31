"""CLI commands for the spec evolution / change management system."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from odk.cli._helpers import format_or_echo
from odk.core.spec_evolution import SpecEvolutionEngine
from odk.output.console import console

change_app = typer.Typer(name="change", help="Spec evolution — propose, track, and archive changes")


def _engine() -> SpecEvolutionEngine:
    """Build a SpecEvolutionEngine instance."""
    return SpecEvolutionEngine()


@change_app.command()
def propose(
    name: str = typer.Argument(..., help="Change name (kebab-case)"),
    mode: str = typer.Option("small", "--mode", "-m", help="Change mode: major or small"),
) -> None:
    """Create a new change proposal with templates."""
    try:
        info = _engine().propose(name, mode, Path.cwd())
    except (FileExistsError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    console.print(f"[green]Created change: {info.name} (mode={info.mode})[/green]")
    console.print(f"  docs/changes/{name}/")


@change_app.command("list")
def list_changes(
    ctx: typer.Context,
    status: str = typer.Option("active", "--status", "-s", help="Filter: active, archived, or all"),
) -> None:
    """List changes filtered by status."""
    changes = _engine().list_changes(Path.cwd(), status)

    if not changes:
        console.print("[yellow]No changes found.[/yellow]")
        return

    data = [c.model_dump(mode="json") for c in changes]
    if format_or_echo(ctx, data):
        return

    table = Table(title="Changes")
    table.add_column("Name", style="cyan")
    table.add_column("Mode")
    table.add_column("Status")
    table.add_column("Created")
    for c in changes:
        table.add_row(c.name, c.mode.value, c.status.value, c.created_at)
    console.print(table)


@change_app.command("status")
def show_status(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Change name"),
) -> None:
    """Show artifact completeness for a change."""
    try:
        artifact_status = _engine().get_change_status(name, Path.cwd())
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    data = artifact_status.model_dump(mode="json")
    if format_or_echo(ctx, data):
        return

    console.print(f"[bold]{name}[/bold]")
    for artifact in artifact_status.required:
        icon = "[green]✓[/green]" if artifact in artifact_status.present else "[red]✗[/red]"
        console.print(f"  {icon} {artifact}")


@change_app.command()
def archive(
    name: str = typer.Argument(..., help="Change name to archive"),
) -> None:
    """Archive a change: merge delta specs into canonical specs."""
    try:
        result = _engine().archive(name, Path.cwd())
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    console.print(f"[green]Archived: {name}[/green]")
    console.print(f"  Operations applied: {result.operations_applied}")
    if result.target_files_modified:
        console.print(f"  Files modified: {', '.join(result.target_files_modified)}")
    console.print(f"  Archive path: {result.archive_path}")


@change_app.command()
def diff(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Change name"),
) -> None:
    """Preview what archiving would do (without applying)."""
    try:
        operations = _engine().diff(name, Path.cwd())
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    if not operations:
        console.print("[yellow]No delta operations found.[/yellow]")
        return

    data = [op.model_dump(mode="json") for op in operations]
    if format_or_echo(ctx, data):
        return

    for op in operations:
        color = {"added": "green", "modified": "yellow", "removed": "red"}.get(op.delta_type.value, "white")
        console.print(f"  [{color}]{op.delta_type.value.upper()}[/{color}] {op.section_heading} -> {op.target_file}")

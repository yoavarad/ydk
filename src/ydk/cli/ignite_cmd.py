"""CLI command for the ignition engine."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from ydk.core.ignition import IgnitionEngine, IgnitionError
from ydk.output.console import console


def ignite_command(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be generated without writing"),
    force: bool = typer.Option(False, "--force", help="Regenerate all files, even developer-owned"),
    skip_verify: bool = typer.Option(
        False, "--skip-verify", help="Skip spec verification gate (for brownfield/inherited specs)"
    ),
) -> None:
    """Generate project skeleton from installed ignition pack and YDK components."""
    project_root = Path.cwd()

    # --- Precondition checks ---
    from ydk.core.state import ProjectState

    state = ProjectState(project_root)

    # Check schemas installed
    schemas_dir = project_root / ".ydk" / "schemas"
    if not schemas_dir.is_dir() or not list(schemas_dir.glob("*.yaml")):
        console.print("[red]Schemas not installed. Run: ydk component init-schemas[/red]")
        raise typer.Exit(1)

    # Check pack installed (supports both new and legacy layout)
    packs_dir = project_root / ".ydk" / "ignition-packs"
    legacy_pack_dir = project_root / ".ydk" / "ignition-pack"
    has_pack = (packs_dir.is_dir() and list(packs_dir.iterdir())) or legacy_pack_dir.is_dir()
    if not has_pack:
        console.print("[red]No ignition pack installed. Run: ydk catalog install <pack-name>[/red]")
        raise typer.Exit(1)

    # Check spec verified (for non-dry-run only)
    if not dry_run:
        if skip_verify:
            console.print("[yellow]⚠ Skipping spec verification gate (--skip-verify)[/yellow]")
        else:
            spec_results = project_root / ".ydk" / "spec-check-results.json"
            if not spec_results.exists():
                console.print(
                    "[red]Error: Spec verification required. Run: ydk spec verify --all-files\n"
                    "Or bypass with: ydk ignite --skip-verify (for inherited/brownfield specs)[/red]"
                )
                raise typer.Exit(1)

    engine = IgnitionEngine(project_root)

    try:
        result = engine.ignite(dry_run=dry_run, force=force)
    except IgnitionError as exc:
        console.print(f"[red]Ignition failed: {exc}[/red]")
        raise typer.Exit(code=1) from None

    # Print report
    if dry_run:
        console.print("[yellow]Dry run — no files written.[/yellow]")

    table = Table(title="Ignition Report")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Files generated", str(result.files_generated))
    table.add_row("Files written", str(result.files_written))
    table.add_row("Files skipped", str(result.files_skipped))
    table.add_row("TODOs registered", str(result.todos_registered))
    table.add_row("Duration", f"{result.duration_seconds}s")
    console.print(table)

    for warning in result.warnings:
        console.print(f"[yellow]⚠ {warning}[/yellow]")

    for error in result.errors:
        console.print(f"[red]✗ {error}[/red]")

    # Only exit 1 for real errors (generator crashes, zero files written).
    # Conflicts with files_written > 0 are demoted to warnings.
    if result.errors and result.files_written == 0:
        raise typer.Exit(code=1)

    # Advance state after successful ignition (non-dry-run)
    if not dry_run:
        state.update(stage="02")

"""CLI command for the ignition engine."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.table import Table

from ydk.core.config import load_config
from ydk.core.ignition import IgnitionEngine, IgnitionError
from ydk.output.console import console


def ignite_command(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be generated without writing"),
    force: bool = typer.Option(False, "--force", help="Regenerate all files, even developer-owned"),
    skip_verify: bool = typer.Option(
        False, "--skip-verify", help="Skip spec verification gate (for brownfield/inherited specs)"
    ),
    answer: Annotated[
        list[str] | None,
        typer.Option(
            "--answer",
            help="Pack init answer KEY=VALUE (repeatable); overrides ignition.init_answers in config",
        ),
    ] = None,
) -> None:
    """Generate project skeleton from installed ignition pack and YDK components."""
    project_root = Path.cwd()

    cli_answers: dict[str, str] = {}
    for item in answer or []:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            console.print(f"[red]Invalid --answer {item!r}: expected KEY=VALUE[/red]")
            raise typer.Exit(1)
        cli_answers[key.strip()] = value

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

    try:
        config_answers = load_config(project_root / ".ydk" / "config.yaml").ignition.init_answers
    except (ValueError, yaml.YAMLError) as exc:
        console.print(f"[red]Invalid .ydk/config.yaml: {exc}[/red]")
        raise typer.Exit(1) from None
    init_answers = {**config_answers, **cli_answers}

    engine = IgnitionEngine(project_root)

    try:
        result = engine.ignite(init_answers=init_answers, dry_run=dry_run, force=force)
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

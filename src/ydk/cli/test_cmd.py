"""CLI commands for test generation and coverage."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from ydk.cli._helpers import format_or_echo
from ydk.core.test_coverage import TestCoverageChecker
from ydk.core.test_generator import ComponentTestGenerator
from ydk.output.console import console

test_app = typer.Typer(name="test", help="Generate tests and check coverage")


def _load_component(component_id: str) -> tuple[dict, dict]:
    """Load manifest and schema for a component ID."""
    from ydk.core.component_registry import ComponentRegistry

    schemas_dir = Path.cwd() / ".ydk" / "schemas"
    components_dir = Path.cwd() / ".ydk" / "components"
    registry = ComponentRegistry(schemas_dir, components_dir)

    manifest_obj = registry.load_component(component_id)
    manifest = manifest_obj.model_dump()

    # Load schema
    schema_ref = manifest.get("schema_ref", "")
    schema_type = schema_ref.removeprefix("ydk:schema:") if schema_ref.startswith("ydk:schema:") else ""
    schemas = registry.load_schemas()
    schema_def = schemas.get(schema_type)
    schema: dict = {}
    if schema_def:
        schema = schema_def.model_dump()
    return manifest, schema


@test_app.command("generate")
def generate(
    component_id: str = typer.Option(..., "--from", help="Component ID to generate tests for"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output file path (default: stdout)"),  # noqa: B008
) -> None:
    """Generate tests from a component manifest."""
    try:
        manifest, schema = _load_component(component_id)
    except Exception as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    generator = ComponentTestGenerator()

    # Determine component type
    parts = component_id.split(":", 2)
    comp_type = parts[1] if len(parts) >= 2 else "unknown"

    if comp_type == "entity":
        result = generator.generate_from_entity(manifest, schema)
    elif comp_type == "route":
        result = generator.generate_from_route(manifest, schema)
    elif comp_type == "error":
        result = generator.generate_from_error(manifest, schema)
    else:
        console.print(f"[red]Unsupported component type: {comp_type}[/red]")
        raise typer.Exit(code=1)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(result.test_code)
        console.print(f"[green]Generated {result.test_count} test(s) → {output}[/green]")
    else:
        typer.echo(result.test_code)


@test_app.command("coverage")
def coverage(ctx: typer.Context) -> None:
    """Show test coverage report for all components."""
    components_dir = Path.cwd() / ".ydk" / "components"
    tests_dir = Path.cwd() / "tests"

    checker = TestCoverageChecker()
    report = checker.check_coverage(components_dir, tests_dir)

    data = report.model_dump()
    if format_or_echo(ctx, data):
        return

    if report.total_components == 0:
        console.print("[yellow]No components found.[/yellow]")
        return

    # Summary table
    table = Table(title="Test Coverage by Type")
    table.add_column("Type", style="cyan")
    table.add_column("Total", justify="right")
    table.add_column("Covered", justify="right")
    table.add_column("Coverage", justify="right")

    for bt in report.by_type:
        pct_str = f"{bt.pct:.0f}%"
        style = "green" if bt.pct >= 80 else ("yellow" if bt.pct >= 50 else "red")
        table.add_row(bt.type_name, str(bt.count), str(bt.covered), f"[{style}]{pct_str}[/{style}]")

    table.add_section()
    total_style = "green" if report.coverage_pct >= 80 else ("yellow" if report.coverage_pct >= 50 else "red")
    table.add_row(
        "[bold]Total[/bold]",
        str(report.total_components),
        str(report.covered),
        f"[{total_style}][bold]{report.coverage_pct:.0f}%[/bold][/{total_style}]",
    )
    console.print(table)

    if report.uncovered_ids:
        console.print(f"\n[yellow]Uncovered ({report.uncovered}):[/yellow]")
        for uid in report.uncovered_ids:
            console.print(f"  • {uid}")

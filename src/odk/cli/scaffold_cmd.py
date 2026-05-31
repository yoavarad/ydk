"""CLI commands for the scaffold engine."""

from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.table import Table

from odk.cli._helpers import format_or_echo
from odk.core.scaffold import ScaffoldEngine, TemplateValidationError
from odk.output.console import console

scaffold_app = typer.Typer(name="scaffold", help="Generate files from templates")


def _make_engine() -> ScaffoldEngine:
    """Build a ScaffoldEngine with project and global template paths."""
    project_templates = Path.cwd() / ".odk" / "templates"
    global_templates = Path(__file__).resolve().parent.parent / "templates"
    return ScaffoldEngine(project_templates, global_templates)


@scaffold_app.command("list")
def list_templates(ctx: typer.Context) -> None:
    """List all available templates."""
    engine = _make_engine()
    templates = engine.list_templates()
    if not templates:
        console.print("[yellow]No templates found.[/yellow]")
        return

    data = [
        {
            "name": t.name,
            "description": t.description,
            "variables": t.variables,
        }
        for t in templates
    ]
    if format_or_echo(ctx, data):
        return

    table = Table(title="Available Templates")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Variables")
    for t in templates:
        var_names = ", ".join(t.variables.keys()) if t.variables else "(none)"
        table.add_row(t.name, t.description, var_names)
    console.print(table)


@scaffold_app.command()
def info(name: str = typer.Argument(..., help="Template name")) -> None:
    """Show template manifest (description + variables)."""
    engine = _make_engine()
    try:
        manifest = engine.get_template(name)
    except KeyError:
        console.print(f"[red]Template not found: {name}[/red]")
        raise typer.Exit(code=1) from None

    console.print(f"[bold cyan]{manifest.name}[/bold cyan]")
    console.print(f"  {manifest.description}")
    if manifest.variables:
        console.print("\n[bold]Variables:[/bold]")
        for var_name, var_desc in manifest.variables.items():
            console.print(f"  [cyan]{var_name}[/cyan]: {var_desc}")
    else:
        console.print("\n  (no variables)")


@scaffold_app.command()
def apply(
    name: str = typer.Argument(..., help="Template name"),
    var: list[str] = typer.Option([], "--var", help="Variable as key=value"),  # noqa: B008
    var_file: Path | None = typer.Option(None, "--var-file", help="YAML file with variables"),  # noqa: B008
    output_dir: Path = typer.Option(Path("."), "--output-dir", "-o", help="Output base directory"),  # noqa: B008
) -> None:
    """Generate files from a template."""
    engine = _make_engine()

    # Build variables dict: var-file first, then --var overrides
    variables: dict[str, str] = {}
    if var_file is not None:
        variables.update(yaml.safe_load(var_file.read_text()))

    for item in var:
        if "=" not in item:
            console.print(f"[red]Invalid --var format (expected key=value): {item}[/red]")
            raise typer.Exit(code=1)
        key, value = item.split("=", 1)
        variables[key] = value

    try:
        files = engine.apply(name, variables)
    except (KeyError, ValueError, TemplateValidationError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    try:
        written = engine.write_files(files, output_dir)
    except FileExistsError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    console.print(f"[green]Generated {len(written)} file(s):[/green]")
    for path in written:
        console.print(f"  {path}")


@scaffold_app.command()
def create(
    name: str = typer.Argument(..., help="Template name"),
    description: str = typer.Option("", "--description", "-d"),
) -> None:
    """Create a new project-specific template."""
    engine = _make_engine()
    project_templates = Path.cwd() / ".odk" / "templates"
    folder = engine.create_template(name, description, project_templates)
    console.print(f"[green]Created template at {folder}[/green]")

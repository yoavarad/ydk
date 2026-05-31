"""odk catalog — browse, install, publish, and manage catalog items."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from odk.cli._helpers import format_or_echo, get_output_format
from odk.core.catalog import LocalCatalogBackend
from odk.core.catalog_search import CatalogSearch
from odk.output.console import console
from odk.output.formatters import OutputFormat, get_formatter

catalog_app = typer.Typer(name="catalog", help="Browse and manage the ODK catalog")


def _default_catalog_dir() -> Path:
    return Path.home() / ".odk" / "catalog"


def _project_root() -> Path:
    return Path.cwd()


@catalog_app.command("search")
def search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search query"),
    tags: Annotated[list[str] | None, typer.Option("--tag", "-t", help="Filter by tag")] = None,
    semantic: bool = typer.Option(False, "--semantic", "-s", help="Use semantic search (requires ChromaDB)"),
) -> None:
    """Search the catalog for items."""
    catalog_dir = _default_catalog_dir()

    if semantic:
        searcher = CatalogSearch(catalog_dir)
        raw_results = searcher.search(query, n_results=20)
        search_data: list[dict[str, str]] = [{"name": n, "score": str(round(s, 3))} for n, s in raw_results]
    else:
        backend = LocalCatalogBackend(catalog_dir)
        items = backend.search(query, tags)
        search_data = [{"name": i.name, "version": i.version, "tags": ", ".join(i.tags)} for i in items]

    fmt = get_output_format(ctx)
    if fmt in (OutputFormat.json, OutputFormat.yaml):
        formatter = get_formatter(fmt)
        typer.echo(formatter.format(search_data))  # ty: ignore[invalid-argument-type]
        return

    if not search_data:
        console.print("[yellow]No items found.[/yellow]")
        return

    from rich.table import Table

    table = Table(title="Catalog Search Results")
    table.add_column("Name", style="bold")
    if semantic:
        table.add_column("Score")
        for entry in search_data:
            table.add_row(entry["name"], entry["score"])
    else:
        table.add_column("Version")
        table.add_column("Tags")
        for entry in search_data:
            table.add_row(entry["name"], entry["version"], entry["tags"])
    console.print(table)


@catalog_app.command("install")
def install(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Catalog item name"),
    version: str | None = typer.Option(None, "--version", "-v", help="Pin to a specific version"),
) -> None:
    """Install a catalog item into the current project."""
    backend = LocalCatalogBackend(_default_catalog_dir())
    project = _project_root()

    # Check for uninstalled referenced dependencies
    uninstalled_deps = backend.check_uninstalled_deps(name, version, project)
    if uninstalled_deps:
        if sys.stdin.isatty():
            console.print(f"[yellow]'{name}' references uninstalled dependencies:[/yellow]")
            for dep in uninstalled_deps:
                console.print(f"  - {dep}")
            if not typer.confirm("Install dependencies too?"):
                raise typer.Exit(code=0)
        # Auto-install dependencies (silently in non-interactive mode)
        for dep in uninstalled_deps:
            try:
                backend.install(dep, None, project)
                if sys.stdin.isatty():
                    console.print(f"  [green]Installed dependency '{dep}'[/green]")
            except ValueError:
                console.print(f"[yellow]Warning: dependency '{dep}' not found in catalog[/yellow]")

    try:
        backend.install(name, version, project)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from None

    if not format_or_echo(ctx, {"installed": name, "version": version}):
        console.print(f"[green]Installed '{name}' into {project / '.odk'}[/green]")


@catalog_app.command("list")
def list_installed(ctx: typer.Context) -> None:
    """List items installed in the current project."""
    backend = LocalCatalogBackend(_default_catalog_dir())
    items = backend.list_installed(_project_root())
    list_data: list[dict[str, str]] = [{"name": i.name, "version": i.version, "tags": ", ".join(i.tags)} for i in items]

    fmt = get_output_format(ctx)
    if fmt in (OutputFormat.json, OutputFormat.yaml):
        formatter = get_formatter(fmt)
        typer.echo(formatter.format(list_data))  # ty: ignore[invalid-argument-type]
        return

    if not list_data:
        console.print("[yellow]No catalog items installed.[/yellow]")
        return

    from rich.table import Table

    table = Table(title="Installed Catalog Items")
    table.add_column("Name", style="bold")
    table.add_column("Version")
    table.add_column("Tags")
    for entry in list_data:
        table.add_row(entry["name"], entry["version"], entry["tags"])
    console.print(table)


@catalog_app.command("info")
def info(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Catalog item name"),
) -> None:
    """Show details about a catalog item."""
    backend = LocalCatalogBackend(_default_catalog_dir())
    item = backend.get(name)
    if item is None:
        console.print(f"[red]Item '{name}' not found in catalog.[/red]")
        raise typer.Exit(code=1)

    # Load the full manifest for detailed info
    from odk.core.catalog import _load_manifest

    manifest = _load_manifest(item.path)
    data: dict[str, object] = {
        "name": item.name,
        "version": item.version,
        "tags": item.tags,
        "path": str(item.path),
    }
    if manifest:
        data["description"] = manifest.description
        if manifest.inputs:
            data["inputs"] = {k: v.model_dump() for k, v in manifest.inputs.items()}
        if manifest.verification_sets:
            data["verification_sets"] = [r.model_dump() for r in manifest.verification_sets]
        if manifest.spec_reviewers:
            data["spec_reviewers"] = [r.model_dump() for r in manifest.spec_reviewers]
        if manifest.component_schemas:
            data["component_schemas"] = [r.model_dump() for r in manifest.component_schemas]

    fmt = get_output_format(ctx)
    if fmt in (OutputFormat.json, OutputFormat.yaml):
        formatter = get_formatter(fmt)
        typer.echo(formatter.format(data))
        return

    console.print(f"[bold]{item.name}[/bold] v{item.version}")
    if manifest and manifest.description:
        console.print(f"  {manifest.description}")
    console.print(f"  Tags: {', '.join(item.tags) or '(none)'}")
    console.print(f"  Path: {item.path}")

    # Show README excerpt if available
    readme = item.path / "README.md"
    if readme.exists():
        text = readme.read_text().strip()
        if text:
            lines = text.split("\n")[:10]
            console.print("\n[dim]--- README (first 10 lines) ---[/dim]")
            for line in lines:
                console.print(f"  {line}")


@catalog_app.command("publish")
def publish(
    ctx: typer.Context,
    path: Path = typer.Argument(help="Path to the catalog item directory"),  # noqa: B008
) -> None:
    """Publish a catalog item (validate + copy to local catalog)."""
    backend = LocalCatalogBackend(_default_catalog_dir())
    try:
        backend.publish(path)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from None

    if not format_or_echo(ctx, {"published": str(path)}):
        console.print(f"[green]Published catalog item from {path}[/green]")


@catalog_app.command("uninstall")
def uninstall(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Catalog item name to remove"),
) -> None:
    """Remove a catalog item from the current project."""
    backend = LocalCatalogBackend(_default_catalog_dir())
    removed = backend.uninstall(name, _project_root())
    if not removed:
        console.print(f"[yellow]Item '{name}' is not installed.[/yellow]")
        raise typer.Exit(code=1)

    if not format_or_echo(ctx, {"uninstalled": name}):
        console.print(f"[green]Uninstalled '{name}'[/green]")

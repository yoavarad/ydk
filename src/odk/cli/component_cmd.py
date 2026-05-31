"""CLI commands for component manifest management."""

from __future__ import annotations

import shutil
from pathlib import Path

import typer
import yaml

from odk.cli._helpers import format_or_echo
from odk.core.component_registry import ComponentRegistry, ComponentRegistryError
from odk.output.console import console

component_app = typer.Typer(name="component", help="Component manifest management")

_DEFAULT_SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


def _make_registry() -> ComponentRegistry:
    """Build a ComponentRegistry from project paths."""
    schemas_dir = Path(".odk") / "schemas"
    components_dir = Path(".odk") / "components"
    return ComponentRegistry(schemas_dir=schemas_dir, components_dir=components_dir)


@component_app.command("list")
def list_components(
    ctx: typer.Context,
    type_filter: str | None = typer.Option(None, "--type", help="Filter by component type"),
) -> None:
    """List all components, optionally filtered by type."""
    registry = _make_registry()
    components = registry.list_components(type_filter=type_filter)

    if not components:
        console.print("[yellow]No components found.[/yellow]")
        return

    data = [{"id": c.full_id, "type": c.type, "namespace": c.namespace, "name": c.name} for c in components]
    if format_or_echo(ctx, data):
        return

    grouped: dict[str, list[str]] = {}
    for c in components:
        grouped.setdefault(c.type, []).append(c.full_id)

    console.print(f"\n[bold]Components: {len(components)} total[/bold]\n")
    for type_name in sorted(grouped):
        ids = sorted(grouped[type_name])
        console.print(f"  [cyan]{type_name}[/cyan] ({len(ids)}):")
        for cid in ids:
            console.print(f"    {cid}")
        console.print()


@component_app.command("show")
def show_component(
    ctx: typer.Context,
    component_id: str = typer.Argument(..., help="Full component ID (odk:type:namespace/name)"),
) -> None:
    """Show a component manifest."""
    registry = _make_registry()
    try:
        manifest = registry.load_component(component_id)
    except ComponentRegistryError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None

    data = manifest.model_dump()
    if format_or_echo(ctx, data):
        return

    path = registry.resolve_id(component_id)
    console.print(f"\n[bold]{component_id}[/bold]")
    console.print(f"[dim]{path}[/dim]\n")
    console.print(path.read_text())


@component_app.command("create")
def create_component(
    type_name: str = typer.Argument(..., help="Component type (e.g. route, entity)"),
    namespace_name: str = typer.Argument(..., help="Namespace/name (e.g. orders/create)"),
) -> None:
    """Create a new component from a schema template."""
    registry = _make_registry()
    try:
        path = registry.create_component(type_name, namespace_name)
    except ComponentRegistryError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None

    component_id = f"odk:{type_name}:{namespace_name}"
    console.print(f"[green]Created component: {component_id}[/green]")
    console.print(f"  Path: {path}")


@component_app.command("validate")
def validate_components(ctx: typer.Context) -> None:
    """Validate ALL components (schema + linker + cross-refs)."""
    from odk.core.component_linker import ComponentLinker

    registry = _make_registry()

    schema_errors = registry.validate_all()
    error_count = sum(len(e) for e in schema_errors.values())

    specs_dir = Path("docs") / "specs"
    linker = ComponentLinker(registry=registry, narratives_dir=specs_dir)
    linker_result = linker.validate_references()

    data = {
        "schema_errors": schema_errors,
        "linker": linker_result.model_dump(),
    }
    if format_or_echo(ctx, data):
        return

    console.print("\n[bold]Schema Enforcement:[/bold]")
    if schema_errors:
        for cid, errs in sorted(schema_errors.items()):
            console.print(f"  [red]ERROR: {cid}[/red]")
            for err in errs:
                console.print(f"    - {err}")
    else:
        total = len(registry.list_components())
        console.print(f"  {total} components validated, 0 errors")

    console.print("\n[bold]Deterministic Linker:[/bold]")
    if linker_result.undefined_refs:
        for ref in linker_result.undefined_refs:
            console.print(f"  [red]Dangling reference: {ref}[/red]")
    if linker_result.orphaned_components:
        for orphan in linker_result.orphaned_components:
            console.print(f"  [yellow]WARNING: Orphaned: {orphan}[/yellow]")
    if linker_result.broken_cross_refs:
        for broken in linker_result.broken_cross_refs:
            console.print(f"  [red]Broken cross-ref: {broken}[/red]")
    if not linker_result.undefined_refs and not linker_result.broken_cross_refs:
        console.print(f"  {len(linker_result.valid_refs)} references validated, 0 errors")

    total_errors = error_count + len(linker_result.undefined_refs) + len(linker_result.broken_cross_refs)
    if total_errors > 0:
        console.print(f"\n[bold red]FAILED[/bold red] ({total_errors} errors)")
        raise typer.Exit(1)
    console.print("\n[bold green]ALL PASSED[/bold green]")


@component_app.command("list-schemas")
def list_schemas(ctx: typer.Context) -> None:
    """List available schemas."""
    registry = _make_registry()
    schemas = registry.list_schemas()

    if not schemas:
        console.print("[yellow]No schemas found. Run 'odk component init-schemas' first.[/yellow]")
        return

    data = [{"name": s.name, "description": s.description, "version": s.version} for s in schemas]
    if format_or_echo(ctx, data):
        return

    console.print(f"\n[bold]Schemas: {len(schemas)} available[/bold]\n")
    for s in schemas:
        console.print(f"  [cyan]{s.name}[/cyan] (v{s.version})")
        console.print(f"    {s.description}")


@component_app.command("show-schema")
def show_schema(
    ctx: typer.Context,
    type_name: str = typer.Argument(..., help="Schema type name (e.g. route, entity)"),
) -> None:
    """Show a schema definition."""
    registry = _make_registry()
    schemas = registry.load_schemas()

    if type_name not in schemas:
        console.print(f"[red]Unknown schema type: {type_name}[/red]")
        raise typer.Exit(1)

    schema = schemas[type_name]
    data = schema.model_dump()
    if format_or_echo(ctx, data):
        return

    console.print(f"\n[bold]{schema.name}[/bold] (v{schema.version})")
    console.print(f"  {schema.description}\n")
    console.print("[bold]Fields:[/bold]")
    for fname, fdef in schema.fields.items():
        req = " [red]*[/red]" if fdef.required else ""
        console.print(f"  [cyan]{fname}[/cyan]{req} ({fdef.type})")
        console.print(f"    {fdef.description}")


@component_app.command("init-schemas")
def init_schemas() -> None:
    """Copy default schemas to project's .odk/schemas/ directory."""
    target_dir = Path(".odk") / "schemas"
    target_dir.mkdir(parents=True, exist_ok=True)

    if not _DEFAULT_SCHEMAS_DIR.is_dir():
        console.print("[red]Default schemas directory not found.[/red]")
        raise typer.Exit(1)

    copied = 0
    for schema_file in sorted(_DEFAULT_SCHEMAS_DIR.glob("*.yaml")):
        dest = target_dir / schema_file.name
        if dest.exists():
            console.print(f"  [yellow]Skipping (exists): {schema_file.name}[/yellow]")
            continue
        shutil.copy2(schema_file, dest)
        console.print(f"  [green]Copied: {schema_file.name}[/green]")
        copied += 1

    console.print(f"\n[bold]{copied} schemas initialized in {target_dir}[/bold]")

    components_dir = Path(".odk") / "components"
    components_dir.mkdir(parents=True, exist_ok=True)

    for schema_file in sorted(_DEFAULT_SCHEMAS_DIR.glob("*.yaml")):
        raw = yaml.safe_load(schema_file.read_text())
        if raw and isinstance(raw, dict) and "name" in raw:
            type_dir = components_dir / raw["name"]
            type_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"[bold]Component directories created in {components_dir}[/bold]")

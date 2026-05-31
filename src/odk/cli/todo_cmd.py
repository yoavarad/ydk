"""CLI commands for TODO management."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.progress_bar import ProgressBar
from rich.table import Table

from odk.cli._helpers import format_or_echo
from odk.core.todo_manager import TodoError, TodoManager
from odk.output.console import console

todo_app = typer.Typer(name="todo", help="Manage ignition TODOs")


def _manager() -> TodoManager:
    return TodoManager(Path.cwd())


@todo_app.command("list")
def list_todos(
    ctx: typer.Context,
    status: str | None = typer.Option(None, "--status", help="Filter by status (open, in-progress, done)"),
) -> None:
    """List all TODOs with status."""
    mgr = _manager()
    items = mgr.list_todos(status=status)

    if not items:
        console.print("[yellow]No TODOs found.[/yellow]")
        return

    data = [t.model_dump(mode="json") for t in items]
    if format_or_echo(ctx, data):
        return

    table = Table(title="ODK TODOs")
    table.add_column("ID", style="bold")
    table.add_column("File")
    table.add_column("Method")
    table.add_column("Status")
    table.add_column("Task")
    table.add_column("Description", max_width=40)

    status_colors = {
        "open": "red",
        "in-progress": "yellow",
        "done": "green",
    }

    for item in items:
        color = status_colors.get(item.status.value, "white")
        table.add_row(
            item.id,
            item.file,
            item.method,
            f"[{color}]{item.status.value}[/{color}]",
            item.task_id or "-",
            item.description[:40] if item.description else "-",
        )

    console.print(table)


@todo_app.command("show")
def show(
    ctx: typer.Context,
    todo_id: str = typer.Argument(..., help="TODO ID (e.g., ODK-TODO-001)"),
) -> None:
    """Show details of a specific TODO."""
    mgr = _manager()
    try:
        item = mgr.get(todo_id)
    except TodoError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None

    data = item.model_dump(mode="json")
    if format_or_echo(ctx, data):
        return

    console.print(f"\n[bold]{item.id}[/bold]")
    console.print(f"  File:        {item.file}")
    console.print(f"  Line:        {item.line}")
    console.print(f"  Method:      {item.method}")
    status_colors = {"open": "red", "in-progress": "yellow", "done": "green"}
    color = status_colors.get(item.status.value, "white")
    console.print(f"  Status:      [{color}]{item.status.value}[/{color}]")
    console.print(f"  Task:        {item.task_id or '-'}")
    console.print(f"  Components:  {', '.join(item.component_refs) or '-'}")
    console.print(f"  Description: {item.description or '-'}")


@todo_app.command("assign")
def assign(
    todo_id: str = typer.Argument(..., help="TODO ID"),
    task_id: str = typer.Argument(..., help="Task ID to link"),
) -> None:
    """Link a TODO to a task."""
    mgr = _manager()
    try:
        mgr.assign(todo_id, task_id)
    except TodoError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
    console.print(f"[green]Assigned {todo_id} to task {task_id}[/green]")


@todo_app.command("done")
def done(
    todo_id: str = typer.Argument(..., help="TODO ID to mark as done"),
) -> None:
    """Mark TODO as done. Verifies NotImplementedError is removed."""
    mgr = _manager()
    try:
        mgr.done(todo_id)
    except TodoError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
    console.print(f"[green]{todo_id} marked as done[/green]")


@todo_app.command("assign-batch")
def assign_batch(
    mapping: str = typer.Argument(..., help="Comma-separated TODO_ID:TASK_ID pairs, or path to YAML file"),
) -> None:
    """Bulk assign TODOs to tasks. Accepts 'ODK-TODO-001:T-001,ODK-TODO-002:T-001' or a YAML file."""
    import json as _json

    mgr = _manager()

    # Load batch mapping for T-xxx resolution
    batch_mapping: dict[str, str] = {}
    mapping_file = Path(".odk") / "batch-mapping.json"
    if mapping_file.exists():
        batch_mapping = _json.loads(mapping_file.read_text())

    def _resolve_task(raw_id: str) -> str:
        """Resolve T-001 placeholder to real issue ID."""
        upper = raw_id.upper()
        if upper.startswith("T-") and upper in batch_mapping:
            return batch_mapping[upper]
        return raw_id

    # Determine if input is a file path or inline string
    assignments: list[tuple[str, str]] = []  # (todo_id, task_id)

    if mapping.endswith(".yaml") or mapping.endswith(".yml"):
        # YAML file mode
        import yaml

        mapping_path = Path(mapping)
        if not mapping_path.is_file():
            console.print(f"[red]File not found: {mapping}[/red]")
            raise typer.Exit(1)
        data = yaml.safe_load(mapping_path.read_text())
        if not isinstance(data, dict) or "assignments" not in data:
            console.print("[red]YAML must contain an 'assignments' key mapping task IDs to TODO lists.[/red]")
            raise typer.Exit(1)
        for task_id_raw, todo_list in data["assignments"].items():
            resolved_task = _resolve_task(str(task_id_raw))
            assignments.extend((str(todo_id), resolved_task) for todo_id in todo_list)
    else:
        # Inline comma-separated mode: ODK-TODO-001:T-001,ODK-TODO-002:T-002
        for pair in mapping.split(","):
            pair = pair.strip()
            if ":" not in pair:
                console.print(f"[red]Invalid pair (missing ':'): {pair}[/red]")
                raise typer.Exit(1)
            todo_id, task_id_raw = pair.rsplit(":", 1)
            assignments.append((todo_id.strip(), _resolve_task(task_id_raw.strip())))

    # Execute assignments
    success = 0
    errors = 0
    for todo_id, task_id in assignments:
        try:
            mgr.assign(todo_id, task_id)
            console.print(f"  [green]OK[/green] {todo_id} -> {task_id}")
            success += 1
        except TodoError as e:
            console.print(f"  [red]FAIL[/red] {todo_id}: {e}")
            errors += 1

    console.print(f"\n[bold]Batch assign: {success} succeeded, {errors} failed[/bold]")
    if errors:
        raise typer.Exit(1)


@todo_app.command("auto-assign")
def auto_assign(
    dry_run: bool = typer.Option(True, "--dry-run/--apply", help="Preview assignments without applying"),
) -> None:
    """Auto-assign TODOs to tasks by matching file paths to task component_refs."""
    import re as _re

    mgr = _manager()
    items = mgr.list_todos(status="open")
    unassigned = [t for t in items if not t.task_id]

    if not unassigned:
        console.print("[yellow]No unassigned open TODOs found.[/yellow]")
        return

    # Load tasks from local backend
    task_component_map: dict[str, list[str]] = {}  # task_id -> component_refs

    # Try local backend tasks
    try:
        from odk.repositories.factory import get_task_repository

        repo = get_task_repository()
        summaries = repo.list_tasks(state="open")
        for s in summaries:
            try:
                detail = repo.get_task(s.id)
                refs = getattr(detail, "component_refs", None) or []
                if refs:
                    task_component_map[s.id] = list(refs)
            except (FileNotFoundError, ValueError):
                pass
    except Exception:
        pass

    if not task_component_map:
        console.print("[yellow]No tasks with component_refs found.[/yellow]")
        return

    def _extract_entity_snake(ref: str) -> str:
        """Extract the entity name from a component ref and snake_case it.

        e.g. 'odk:contract:strategy/StrategyService' -> 'strategy_service'
        """
        # Get last segment after /
        if "/" in ref:
            entity = ref.rsplit("/", 1)[1]
        elif ":" in ref:
            entity = ref.rsplit(":", 1)[1]
        else:
            entity = ref
        # Convert PascalCase/camelCase to snake_case
        s1 = _re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", entity)
        return _re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    # Build assignments: match TODO file paths to task component_refs
    assignments: list[tuple[str, str]] = []  # (todo_id, task_id)
    for todo in unassigned:
        file_lower = todo.file.lower()
        best_match: str | None = None
        for task_id, refs in task_component_map.items():
            for ref in refs:
                entity_snake = _extract_entity_snake(ref)
                if entity_snake and entity_snake in file_lower:
                    best_match = task_id
                    break
            if best_match:
                break
        if best_match:
            assignments.append((todo.id, best_match))

    if not assignments:
        console.print("[yellow]No matches found between TODOs and task component_refs.[/yellow]")
        return

    # Display or apply
    table = Table(title="Auto-Assign Proposals" if dry_run else "Auto-Assign Results")
    table.add_column("TODO ID", style="bold")
    table.add_column("File")
    table.add_column("Task ID")

    for todo_id, task_id in assignments:
        todo = mgr.get(todo_id)
        if dry_run:
            table.add_row(todo_id, todo.file, task_id)
        else:
            try:
                mgr.assign(todo_id, task_id)
                table.add_row(todo_id, todo.file, f"[green]{task_id}[/green]")
            except TodoError as e:
                table.add_row(todo_id, todo.file, f"[red]FAILED: {e}[/red]")

    console.print(table)
    unmatched = len(unassigned) - len(assignments)
    console.print(f"\n[bold]{len(assignments)} assigned, {unmatched} unmatched[/bold]")
    if dry_run:
        console.print("[dim]Run with --apply to execute assignments.[/dim]")


@todo_app.command("coverage")
def coverage(ctx: typer.Context) -> None:
    """Show TODO completion coverage."""
    mgr = _manager()
    stats = mgr.coverage()

    if format_or_echo(ctx, stats):
        return

    total = stats["total"]
    if total == 0:
        console.print("[yellow]No TODOs registered.[/yellow]")
        return

    console.print("\n[bold]TODO Coverage[/bold]")
    console.print(f"  Total:       {total}")
    console.print(f"  [red]Open:        {stats['open']}[/red]")
    console.print(f"  [yellow]In-Progress: {stats['in_progress']}[/yellow]")
    console.print(f"  [green]Done:        {stats['done']}[/green]")
    console.print(f"  Percentage:  {stats['percentage']}%")

    # Progress bar
    bar = ProgressBar(total=total, completed=stats["done"], width=40)
    console.print()
    console.print(bar)
    console.print()

"""ydk task — task management and validation."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

import typer

from ydk.cli._helpers import format_or_echo
from ydk.core.task_validator import validate_dag
from ydk.models.task import Task
from ydk.output.console import console

if TYPE_CHECKING:
    from ydk.core.complexity_scorer import LLMProvider
    from ydk.core.task_lifecycle import TaskLifecycle
    from ydk.models.complexity import ComplexityScore
    from ydk.models.gate import Gate
    from ydk.models.pm import Dependency
    from ydk.repositories.protocols import LifecycleTaskRepository


def _validate_component_refs_cli(refs: list[str], project_root: Path) -> None:
    """Validate each component ref resolves to an existing file, or raise BadParameter."""
    from ydk.core.task_validator import validate_component_ref

    components_dir = project_root / ".ydk" / "components"
    for ref in refs:
        err = validate_component_ref(ref, components_dir)
        if err:
            raise typer.BadParameter(err)


def _validate_spec_refs_cli(refs: list[str], project_root: Path) -> None:
    """Validate each spec ref exists, or raise BadParameter."""
    from ydk.core.task_validator import validate_spec_ref

    for ref in refs:
        err = validate_spec_ref(ref, project_root)
        if err:
            raise typer.BadParameter(err)


def _is_human_format(ctx: typer.Context) -> bool:
    """Return True when the output format is human (not json/yaml)."""
    from ydk.cli._helpers import get_output_format
    from ydk.output.formatters import OutputFormat

    return get_output_format(ctx) == OutputFormat.human


def _warn_missing_acceptance(acceptance: list[str], ctx: typer.Context) -> None:
    """Print warning when acceptance criteria are empty (human format only)."""
    if not acceptance and _is_human_format(ctx):
        typer.echo(
            "WARNING: Task has no acceptance criteria. Every task SHOULD have testable acceptance criteria.",
            err=True,
        )


def _warn_missing_test_strategy(test_strategy: str, ctx: typer.Context) -> None:
    """Print warning when test strategy is empty (human format only)."""
    if not test_strategy and _is_human_format(ctx):
        typer.echo("WARNING: Task has no test strategy.", err=True)


task_app = typer.Typer(name="task", help="Task management and validation")


def _resolve_task_id(raw_id: str) -> str:
    """Resolve T-001 placeholder to GitHub issue number via batch mapping.

    If a batch-mapping.json exists and contains the ID, returns the resolved value.
    If no mapping file exists or the ID is not in the mapping, returns the raw ID
    as-is (it may be a valid local-backend task ID like T-001).
    """
    import json as _json

    if raw_id.startswith("T-") or raw_id.startswith("t-"):
        mapping_file = Path(".ydk") / "batch-mapping.json"
        if mapping_file.exists():
            try:
                mapping = _json.loads(mapping_file.read_text())
                resolved = mapping.get(raw_id.upper())
                if resolved:
                    return resolved
            except (ValueError, OSError):
                pass
    return raw_id


_VALID_DEP_TYPES = frozenset(
    {
        "blocks",
        "validates",
        "caused-by",
        "conditional-blocks",
        "waits-for",
        "discovered-from",
        "supersedes",
        "related",
    }
)


def _parse_depends_on_arg(raw: list[str]) -> list[str | Dependency]:
    """Parse --depends-on values supporting ``T-001:validates`` syntax.

    Format: ``"ID:type,ID:type"`` where type defaults to ``blocks``.
    Supported types: blocks, validates, caused-by, conditional-blocks,
    waits-for, discovered-from, supersedes, related.

    If no colon, or if the type is ``blocks`` (the default), returns a bare
    string for backward compatibility.  Otherwise returns a Dependency object.

    Raises ``typer.BadParameter`` if the dependency type is invalid.
    """
    from ydk.models.pm import Dependency, DependencyType

    result: list[str | Dependency] = []
    for item in raw:
        if ":" in item:
            task_id, type_str = item.rsplit(":", 1)
            if type_str not in _VALID_DEP_TYPES:
                valid = ", ".join(sorted(_VALID_DEP_TYPES))
                raise typer.BadParameter(f"Invalid dependency type '{type_str}'. Must be one of: {valid}")
            dep_type = DependencyType(type_str)
            if dep_type == DependencyType.BLOCKS:
                result.append(task_id)
            else:
                result.append(Dependency(task_id=task_id, type=dep_type))
        else:
            result.append(item)
    return result


def _build_lifecycle() -> TaskLifecycle:
    """Construct a TaskLifecycle with default dependencies from config."""
    from ydk.core.config import load_config
    from ydk.core.events import EventBus
    from ydk.core.git_worktree import WorktreeManager
    from ydk.core.task_lifecycle import TaskLifecycle as _TaskLifecycle
    from ydk.core.verifier import Verifier
    from ydk.repositories.factory import get_task_repository

    cfg = load_config()
    root = Path(".")
    repo = get_task_repository()
    events = EventBus()
    worktree_mgr = WorktreeManager(root)
    enabled = cfg.verification.enabled or None
    verifier = Verifier(project_root=root, enabled_plugins=enabled)
    use_worktrees = cfg.execution.worktree_isolation if hasattr(cfg, "execution") else True
    return _TaskLifecycle(
        repo=repo,
        events=events,
        worktree_mgr=worktree_mgr,
        verifier=verifier,
        project_root=root,
        worktree_isolation=use_worktrees,
    )


def _get_repo() -> LifecycleTaskRepository:
    """Lazily import and return the task repository."""
    from ydk.repositories.factory import get_task_repository

    return get_task_repository()


@task_app.command()
def create(
    ctx: typer.Context,
    title: str = typer.Option(..., "--title"),
    story_id: str = typer.Option(..., "--story"),
    description: str = typer.Option("", "--description"),
    description_file: str | None = typer.Option(
        None, "--description-file", help="Read description from file (mutually exclusive with --description)"
    ),
    spec_refs: list[str] = typer.Option([], "--spec-refs"),  # noqa: B008
    component_refs: list[str] = typer.Option([], "--component-refs"),  # noqa: B008
    acceptance: list[str] = typer.Option([], "--acceptance"),  # noqa: B008
    depends_on: list[str] = typer.Option(  # noqa: B008
        [],
        "--depends-on",
        help='Dependencies as "ID:type,ID:type". Type defaults to blocks. '
        "Supported: blocks, validates, caused-by, conditional-blocks, "
        "waits-for, discovered-from, supersedes, related.",
    ),
    test_strategy: str = typer.Option("", "--test-strategy"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate and show what would be created without calling the API"
    ),
) -> None:
    """Create a new task.

    Use --depends-on T-001:validates to specify dependency type.
    Default type is 'blocks'. Supported types: blocks, validates,
    caused-by, conditional-blocks, waits-for, discovered-from,
    supersedes, related.
    """
    from ydk.models.pm import Dependency as _Dep
    from ydk.models.pm import TaskCreate

    if description and description_file:
        typer.echo("Error: --description and --description-file are mutually exclusive.", err=True)
        raise typer.Exit(code=1)

    resolved_description = description
    if description_file is not None:
        desc_path = Path(description_file)
        if not desc_path.is_file():
            typer.echo(f"Error: description file not found: {description_file}", err=True)
            raise typer.Exit(code=1)
        resolved_description = desc_path.read_text(encoding="utf-8").strip()

    # Validate component_refs and spec_refs at creation time
    project_root = Path(".")
    if component_refs:
        _validate_component_refs_cli(component_refs, project_root)
    if spec_refs:
        _validate_spec_refs_cli(spec_refs, project_root)

    # Warn on missing acceptance / test-strategy
    _warn_missing_acceptance(list(acceptance), ctx)
    _warn_missing_test_strategy(test_strategy, ctx)

    parsed_deps = _parse_depends_on_arg(depends_on)

    if dry_run:
        console.print("[yellow]Dry run -- no task will be created[/yellow]")
        console.print(f"  Title: {title}")
        console.print(f"  Story: {story_id}")
        console.print(f"  Dependencies: {parsed_deps}")
        if spec_refs:
            console.print(f"  Spec refs: {spec_refs}")
        if component_refs:
            console.print(f"  Component refs: {component_refs}")
        raise typer.Exit(0)

    repo = _get_repo()

    # Validate dependencies exist and are not self-referential
    for dep in parsed_deps:
        dep_id: str = dep.task_id if isinstance(dep, _Dep) else dep
        try:
            repo.get_task(dep_id)
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            typer.echo(f"Error: dependency '{dep_id}' not found: {exc}", err=True)
            raise typer.Exit(code=1) from None

    task = TaskCreate(
        title=title,
        story_id=story_id,
        description=resolved_description,
        spec_refs=spec_refs,
        component_refs=component_refs,
        acceptance_criteria=list(acceptance),  # type: ignore[arg-type]
        dependencies=parsed_deps,
        test_strategy=test_strategy,
    )
    detail = repo.create_task(task)

    if not format_or_echo(ctx, detail):
        task_label = detail.id or f"#{detail.number}"
        console.print(f"[green]Created task {task_label}:[/green] {detail.title}")


def _normalize_refs(value: object) -> list[str]:
    """Ensure refs is always a list — wrap scalars."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _validate_batch_yaml(data: dict[str, object], project_root: Path | None = None) -> list[str]:
    """Validate a batch YAML structure. Returns a list of error strings (empty = valid).

    Checks:
    - Required fields present on each entity
    - All depends_on reference IDs that exist in the same YAML
    - All dependency types are valid
    - No self-dependencies
    - spec_refs point to existing files (when project_root is provided)
    """
    errors: list[str] = []

    # Collect all defined IDs
    defined_ids: set[str] = set()
    for epic in data.get("epics", []) or []:  # ty: ignore[not-iterable]
        if not isinstance(epic, dict):
            errors.append("Epic entry is not a mapping")
            continue
        eid = epic.get("id", "")
        if not eid:
            errors.append(f"Epic missing 'id': {epic.get('title', '?')}")
        elif not epic.get("title"):
            errors.append(f"Epic '{eid}' missing 'title'")
        if eid:
            defined_ids.add(eid)

    for story in data.get("stories", []) or []:  # ty: ignore[not-iterable]
        if not isinstance(story, dict):
            errors.append("Story entry is not a mapping")
            continue
        sid = story.get("id", "")
        if not sid:
            errors.append(f"Story missing 'id': {story.get('title', '?')}")
        elif not story.get("title"):
            errors.append(f"Story '{sid}' missing 'title'")
        if sid:
            defined_ids.add(sid)
        # Validate epic reference
        epic_ref = story.get("epic", "")
        if epic_ref and epic_ref not in defined_ids:
            errors.append(f"Story '{sid}' references undefined epic '{epic_ref}'")

    for task in data.get("tasks", []) or []:  # ty: ignore[not-iterable]
        if not isinstance(task, dict):
            errors.append("Task entry is not a mapping")
            continue
        tid = task.get("id", "")
        if not tid:
            errors.append(f"Task missing 'id': {task.get('title', '?')}")
        elif not task.get("title"):
            errors.append(f"Task '{tid}' missing 'title'")
        if tid:
            defined_ids.add(tid)

    # Second pass: validate task dependencies
    for task in data.get("tasks", []) or []:  # ty: ignore[not-iterable]
        if not isinstance(task, dict):
            continue
        tid = task.get("id", "")
        for dep in task.get("depends_on", []) or []:
            parts = str(dep).split(":")
            dep_ref = parts[0]
            dep_type = parts[1] if len(parts) > 1 else "blocks"
            if dep_ref == tid:
                errors.append(f"Task '{tid}' has self-dependency")
            if dep_ref not in defined_ids:
                errors.append(f"Task '{tid}' depends on undefined ID '{dep_ref}'")
            if dep_type not in _VALID_DEP_TYPES:
                errors.append(f"Task '{tid}' has invalid dependency type '{dep_type}'")

    # Validate spec_refs exist on disk (when project_root is provided)
    if project_root is not None:
        from ydk.core.config import load_config as _load_cfg

        try:
            cfg = _load_cfg()
            spec_location = cfg.project.spec_location
        except Exception:
            spec_location = "docs/specs"

        for entity_type in ("epics", "stories", "tasks"):
            raw_items = data.get(entity_type, [])
            entities = cast("list[object]", raw_items if isinstance(raw_items, list) else [])
            for item in entities:
                if not isinstance(item, dict):
                    continue
                item_map = cast("dict[str, object]", item)
                item_id = item_map.get("id", "?")
                for ref in _normalize_refs(item_map.get("spec_refs")):
                    spec_path = project_root / ref
                    if not spec_path.is_file():
                        # Also try relative to spec_location
                        alt_path = project_root / spec_location / ref
                        if not alt_path.is_file():
                            errors.append(f"Task '{item_id}': spec_ref '{ref}' not found at {spec_path}")

    # Validate we have at least one entity
    has_epics = bool(data.get("epics"))
    has_stories = bool(data.get("stories"))
    has_tasks = bool(data.get("tasks"))
    if not has_epics and not has_stories and not has_tasks:
        errors.append("YAML must have at least one of: epics, stories, tasks")

    return errors


def _ensure_labels(repo: object) -> None:
    """Ensure required labels exist. Works for GitHub repos that have add_label."""
    required_labels = {
        "epic": "7057ff",
        "story": "0075ca",
        "task": "008672",
        "blocked-by-code": "d73a4a",
        "blocked-by-decision": "fbca04",
    }
    # Only GitHub repos support label creation via gh CLI
    try:
        from ydk.repositories.github._helpers import run_gh

        for label, color in required_labels.items():
            run_gh(["gh", "label", "create", label, "--color", color, "--force"])
    except ImportError:
        pass  # Local repos don't need label creation


@task_app.command("create-batch")
def create_batch(
    ctx: typer.Context,
    from_file: str = typer.Option(..., "--from", help="YAML file with batch definitions"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate and show what would be created without calling the API"
    ),
) -> None:
    """Create epics, stories, and tasks from a YAML file using two-pass dependency resolution.

    The YAML file supports top-level ``epics``, ``stories``, and ``tasks`` keys.
    Each entity has an ``id`` field used for cross-referencing within the file.
    Task dependencies are resolved to real IDs after all issues are created.
    """
    from rich.table import Table

    from ydk.models.pm import EpicCreate, StoryCreate, TaskCreate

    from_path = Path(from_file)
    if not from_path.is_file():
        typer.echo(f"Error: file not found: {from_file}", err=True)
        raise typer.Exit(code=1)

    try:
        import yaml

        data = yaml.safe_load(from_path.read_text(encoding="utf-8"))
    except Exception as exc:
        typer.echo(f"Error parsing YAML: {exc}", err=True)
        raise typer.Exit(code=1) from None

    if not isinstance(data, dict):
        typer.echo("Error: YAML must be a mapping.", err=True)
        raise typer.Exit(code=1)

    # --- Validation ---
    project_root = Path(".")
    validation_errors = _validate_batch_yaml(data, project_root=project_root)
    if validation_errors:
        for err in validation_errors:
            console.print(f"  [red]ERROR[/red] {err}")
        raise typer.Exit(code=1)

    # --- Dry run ---
    if dry_run:
        console.print("[yellow]Dry run -- no issues will be created[/yellow]")
        table = Table(title="Batch Dry Run Summary")
        table.add_column("Type", style="bold")
        table.add_column("ID")
        table.add_column("Title")
        for epic in data.get("epics", []) or []:
            table.add_row("epic", str(epic["id"]), str(epic["title"]))
        for story in data.get("stories", []) or []:
            table.add_row("story", str(story["id"]), str(story["title"]))
        for task in data.get("tasks", []) or []:
            table.add_row("task", str(task["id"]), str(task["title"]))
        console.print(table)
        raise typer.Exit(0)

    # --- Ensure labels exist ---
    _ensure_labels(_get_repo())

    # --- Pass 1: Create all issues and collect ID mappings ---
    id_map: dict[str, str] = {}  # placeholder_id -> real_id (e.g. "epic-phase-a" -> "E-001")
    results: list[tuple[str, str, str, str]] = []  # (type, placeholder, real_id, status)

    from ydk.repositories.factory import get_epic_repository, get_story_repository

    epic_repo = get_epic_repository()
    story_repo = get_story_repository()
    task_repo = _get_repo()

    # Create epics
    for epic_defn in data.get("epics", []) or []:
        placeholder = str(epic_defn["id"])
        try:
            epic = EpicCreate(
                title=str(epic_defn["title"]),
                description=str(epic_defn.get("description", "")),
                spec_refs=_normalize_refs(epic_defn.get("spec_refs")),
            )
            detail = epic_repo.create_epic(epic)
            real_id = detail.id or f"#{detail.number}"
            id_map[placeholder] = real_id
            results.append(("epic", placeholder, real_id, "OK"))
        except Exception as exc:
            results.append(("epic", placeholder, "?", f"FAILED: {exc}"))

    # Create stories (resolving epic references)
    for story_defn in data.get("stories", []) or []:
        placeholder = str(story_defn["id"])
        try:
            raw_epic = str(story_defn.get("epic", ""))
            resolved_epic = id_map.get(raw_epic, raw_epic) if raw_epic else None
            story = StoryCreate(
                title=str(story_defn["title"]),
                epic_id=resolved_epic,
                description=str(story_defn.get("description", "")),
                spec_refs=_normalize_refs(story_defn.get("spec_refs")),
                component_refs=_normalize_refs(story_defn.get("component_refs")),
                acceptance_criteria=list(story_defn.get("acceptance") or []),
            )
            detail = story_repo.create_story(story)
            real_id = detail.id or f"#{detail.number}"
            id_map[placeholder] = real_id
            results.append(("story", placeholder, real_id, "OK"))
        except Exception as exc:
            results.append(("story", placeholder, "?", f"FAILED: {exc}"))

    # Create tasks (resolving story references; deps stay as placeholders for now)
    for task_defn in data.get("tasks", []) or []:
        placeholder = str(task_defn["id"])
        try:
            raw_story = str(task_defn.get("story", ""))
            resolved_story = id_map.get(raw_story, raw_story) if raw_story else None
            # Parse depends_on but don't resolve yet -- just store raw for creation
            raw_deps = task_defn.get("depends_on") or []
            parsed_deps = _parse_depends_on_arg([str(d) for d in raw_deps])
            task = TaskCreate(
                title=str(task_defn["title"]),
                story_id=resolved_story,
                description=str(task_defn.get("description", "")),
                component_refs=_normalize_refs(task_defn.get("component_refs")),
                spec_refs=_normalize_refs(task_defn.get("spec_refs")),
                acceptance_criteria=list(task_defn.get("acceptance") or []),
                dependencies=parsed_deps,
                test_strategy=str(task_defn.get("test_strategy", "")),
            )
            detail = task_repo.create_task(task)
            real_id = detail.id or f"#{detail.number}"
            id_map[placeholder] = real_id
            results.append(("task", placeholder, real_id, "OK"))
        except Exception as exc:
            results.append(("task", placeholder, "?", f"FAILED: {exc}"))

    # --- Write batch mapping file (.ydk/batch-mapping.json) ---
    import json as _json_batch

    mapping_dir = Path(".ydk")
    mapping_dir.mkdir(parents=True, exist_ok=True)
    mapping_file = mapping_dir / "batch-mapping.json"
    mapping_file.write_text(_json_batch.dumps(id_map, indent=2))

    # --- Pass 2: Update task dependencies with resolved IDs ---
    for task_defn in data.get("tasks", []) or []:
        placeholder = str(task_defn["id"])
        raw_deps = task_defn.get("depends_on") or []
        if not raw_deps:
            continue
        real_task_id = id_map.get(placeholder)
        if not real_task_id:
            continue  # Task creation failed in pass 1

        resolved_deps: list[str] = []
        for dep in raw_deps:
            parts = str(dep).split(":")
            dep_placeholder = parts[0]
            dep_type = parts[1] if len(parts) > 1 else "blocks"
            resolved_id = id_map.get(dep_placeholder, dep_placeholder)
            resolved_deps.append(f"{resolved_id}:{dep_type}")

        try:
            parsed_resolved = _parse_depends_on_arg(resolved_deps)
            task_repo.update_frontmatter(real_task_id, {"dependencies": _serialize_deps_for_update(parsed_resolved)})
        except Exception as exc:
            typer.echo(f"  [warn] Failed to update deps for {placeholder} → {real_task_id}: {exc}", err=True)

    # --- Output ---
    if format_or_echo(
        ctx,
        [{"type": r[0], "placeholder": r[1], "id": r[2], "status": r[3]} for r in results],
    ):
        return

    table = Table(title=f"Batch Create Results ({len(results)} items)")
    table.add_column("Type", style="bold")
    table.add_column("Placeholder")
    table.add_column("ID", style="bold")
    table.add_column("Status")

    for item_type, placeholder, real_id, status in results:
        style = "green" if status == "OK" else "red"
        table.add_row(item_type, placeholder, real_id, f"[{style}]{status}[/{style}]")

    console.print(table)

    ok_count = sum(1 for _, _, _, s in results if s == "OK")
    fail_count = len(results) - ok_count
    if fail_count:
        typer.echo(f"\n{ok_count} created, {fail_count} failed.", err=True)
        raise typer.Exit(code=1)


def _serialize_deps_for_update(
    deps: list[str | Dependency],
) -> list[str | dict[str, str]]:
    """Serialize parsed dependencies for frontmatter update."""
    from ydk.models.pm import Dependency as _Dep

    result: list[str | dict[str, str]] = []
    for dep in deps:
        if isinstance(dep, _Dep):
            result.append({"task_id": dep.task_id, "type": dep.type.value})
        else:
            result.append(str(dep))
    return result


@task_app.command()
def start(
    task_id: str = typer.Argument(..., help="Task ID to start"),
    session_id: str | None = typer.Option(None, "--session-id", help="Claude Code session ID"),
    base: str | None = typer.Option(
        None, "--base", "-b", help="Base branch to create worktree from (default: current branch)"
    ),
    force: bool = typer.Option(False, "--force", help="Force restart even if task shows in-progress"),
) -> None:
    """Start a task: create worktree, claim, explore."""
    task_id = _resolve_task_id(task_id)

    # Precondition: ignition must have been done (todos.yaml must exist)
    if not (Path(".ydk") / "todos.yaml").exists():
        console.print("[red]No TODO registry found. Run Stage 01.5 (ydk ignite) first.[/red]")
        raise typer.Exit(1)

    lc = _build_lifecycle()
    try:
        result = lc.start(task_id, session_id=session_id, base_branch=base, force=force)
        typer.echo(f"Started task {task_id}")
        typer.echo(f"Worktree: {result['worktree']}")
        if session_id:
            typer.echo(f"Session: {session_id}")
    except (ValueError, FileNotFoundError, KeyError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None

    # Advance state to execution stage
    from ydk.core.state import ProjectState

    _state = ProjectState(Path("."))
    _current = _state.read()
    if _current.get("stage") in ("02", "01.5"):
        _state.update(stage="03")

    # Check for existing PR review comments
    try:
        comments = _fetch_review_comments(task_id)
        unresolved = [c for c in comments if not c.get("resolved", False)]
        if unresolved:
            # Find PR number for display
            import json
            import subprocess as _sp

            find_cmd = ["gh", "pr", "list", "--head", f"task/{task_id}", "--json", "number", "--state", "all"]
            pr_result = _sp.run(find_cmd, capture_output=True, text=True)
            pr_num = "?"
            if pr_result.returncode == 0:
                try:
                    prs = json.loads(pr_result.stdout)
                    if prs:
                        pr_num = str(prs[0]["number"])
                except json.JSONDecodeError:
                    pass

            typer.echo(f"⚠ Existing PR #{pr_num} found with {len(unresolved)} unresolved review comment(s):")
            for i, c in enumerate(unresolved, 1):
                location = c.get("path", "General")
                if c.get("line"):
                    location = f"{location}:{c['line']}"
                author = c.get("author", "unknown")
                body = str(c.get("body", "")).split("\n")[0][:80]
                typer.echo(f'  {i}. {location} — "{body}" ({author})')
            typer.echo("Address these comments before making new changes.")
    except Exception:
        pass  # Review comments are advisory — don't break task start

    # Auto-bootstrap memory if configured
    try:
        from ydk.core.config import load_config

        cfg = load_config()
        if cfg.memory.auto_bootstrap:
            from ydk.cli.memory_cmd import _get_engine

            engine = _get_engine(cfg)
            from ydk.repositories.factory import get_task_repository

            repo = get_task_repository()
            task = repo.get_task(task_id)
            description = task.description if hasattr(task, "description") and task.description else task.title
            spec_refs = task.spec_refs if hasattr(task, "spec_refs") else []
            context = engine.bootstrap(description, spec_refs or [])  # ty: ignore[unresolved-attribute]  # MemoryEngine is optional dep
            if context:
                typer.echo(f"Memory: bootstrapped {len(context)} context entries for {task_id}")
    except (ImportError, Exception):
        # Memory is optional — don't break task start if it fails
        pass


@task_app.command()
def comment(
    task_id: str = typer.Argument(..., help="Task ID"),
    message: str = typer.Argument(..., help="Comment message"),
) -> None:
    """Post comment to task issue (replaces plan and progress)."""
    task_id = _resolve_task_id(task_id)
    lc = _build_lifecycle()
    try:
        lc.progress(task_id, message)
        typer.echo(f"Comment posted to {task_id}")
    except (ValueError, FileNotFoundError, KeyError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None


@task_app.command()
def block(
    task_id: str = typer.Argument(..., help="Task ID"),
    reason: str = typer.Option(..., help="Block reason (code or decision)"),
    detail: str = typer.Option(..., help="Block detail"),
) -> None:
    """Mark task as blocked."""
    task_id = _resolve_task_id(task_id)
    lc = _build_lifecycle()
    try:
        lc.block(task_id, reason, detail)
        typer.echo(f"Task {task_id} blocked: {reason}")
    except (ValueError, FileNotFoundError, KeyError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None


@task_app.command()
def unblock(
    task_id: str = typer.Argument(..., help="Task ID to unblock"),
) -> None:
    """Resume a blocked task."""
    repo = _get_repo()
    try:
        repo.update_status(task_id, "in-progress")
        repo.remove_label(task_id, "blocked-by-code")
        repo.remove_label(task_id, "blocked-by-decision")
        repo.add_label(task_id, "in-progress")
        repo.add_comment(task_id, "Task unblocked. Resuming.")
        typer.echo(f"Task {task_id} unblocked.")
    except (ValueError, FileNotFoundError, KeyError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None


@task_app.command()
def done(
    task_id: str = typer.Argument(..., help="Task ID to complete"),
    summary: str | None = typer.Option(None, "--summary", help="Agent narrative summary for the PR body"),
    skip_plugins: list[str] = typer.Option(  # noqa: B008
        [], "--skip-plugin", help="Skip a plugin (only if it demonstrably fails)"
    ),
) -> None:
    """Complete task: verify, create PR, post proof."""
    task_id = _resolve_task_id(task_id)
    try:
        lc = _build_lifecycle()
    except Exception as e:
        console.print(f"[red]Failed to initialize task lifecycle: {e}[/red]")
        raise typer.Exit(1) from None
    try:
        result = lc.done(task_id, summary=summary, skip_plugins=skip_plugins or None)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1) from None
    except Exception as exc:
        console.print(f"[red]Unexpected error during task done: {exc}[/red]")
        raise typer.Exit(code=1) from None

    if result.get("passed"):
        console.print("[green]✓ All verifications passed[/green]")
        console.print(f"[green]✓ PR created: {result.get('pr_url', 'N/A')}[/green]")
        if result.get("todo_warnings"):
            for w in result["todo_warnings"]:
                console.print(f"[yellow]⚠ {w}[/yellow]")
    else:
        console.print("[red]✗ Verification failed[/red]")
        report = result.get("report")
        if report:
            for check in report.checks:
                status = "[green]✓[/green]" if check.passed else "[red]✗[/red]"
                console.print(f"  {status} {check.name} ({check.duration_seconds}s)")
                if not check.passed:
                    lines = check.output.strip().splitlines()[:3]
                    for line in lines:
                        console.print(f"    {line}")
        if result.get("error"):
            console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    # Check if all tasks are done -> advance to stage 04 (learning)
    try:
        from ydk.core.state import ProjectState as _PS

        _done_state = _PS(Path("."))
        _done_current = _done_state.read()
        if _done_current.get("stage") == "03":
            repo = _get_repo()
            open_tasks = repo.list_tasks(state="open")
            in_progress = repo.list_tasks(state="in-progress")
            if not open_tasks and not in_progress:
                _done_state.update(stage="04")
    except Exception:
        pass  # State advancement is advisory, don't break task done

    # Auto-extract memories if configured
    try:
        from ydk.core.config import load_config

        cfg = load_config()
        if cfg.memory.auto_extract:
            from ydk.cli.memory_cmd import _get_engine, _get_extractor

            engine = _get_engine(cfg)
            extractor = _get_extractor()

            # Try session_id from task metadata first, then fallback
            jsonl_path = _find_session_jsonl(task_id)
            if jsonl_path is None:
                jsonl_path = Path(f".ydk/sessions/{task_id}.jsonl")
            if jsonl_path.is_file():
                memories = extractor.extract(task_id=task_id, jsonl_path=jsonl_path)  # ty: ignore[unresolved-attribute]  # MemoryExtractor is optional dep
                if memories:
                    engine.store(memories)  # ty: ignore[unresolved-attribute]  # MemoryEngine is optional dep
                    typer.echo(f"Memory: extracted {len(memories)} learnings from {task_id}")
    except (ImportError, Exception):
        # Memory is optional — don't break task done if it fails
        pass


def _find_session_jsonl(task_id: str) -> Path | None:
    """Find Claude Code session JSONL for a task.

    Searches for session_id in task comments, then finds the
    corresponding JSONL file in ~/.claude/projects/.
    """
    try:
        repo = _get_repo()
        task = repo.get_task(task_id)

        # Check if session_id is stored
        session_id = getattr(task, "session_id", None)
        if not session_id:
            return None

        # Glob search for JSONL in Claude Code projects
        claude_projects = Path.home() / ".claude" / "projects"
        if claude_projects.is_dir():
            for jsonl in claude_projects.rglob(f"{session_id}.jsonl"):
                return jsonl
    except Exception:
        pass
    return None


@task_app.command("add-gate")
def add_gate(
    task_id: str = typer.Argument(..., help="Task ID"),
    gate_type: str = typer.Option(..., "--type", help="Gate type"),
    config: list[str] = typer.Option([], "--config", help="Key=value config pairs"),  # noqa: B008
    description: str = typer.Option("", "--description", help="Gate description"),
) -> None:
    """Add an external event gate to a task."""
    task_id = _resolve_task_id(task_id)
    import uuid

    from ydk.models.gate import Gate as _Gate
    from ydk.models.gate import GateType

    repo = _get_repo()
    try:
        task = repo.get_task(task_id)
        gate_id = f"G-{uuid.uuid4().hex[:8]}"
        parsed_config: dict[str, str] = {}
        for item in config:
            if "=" in item:
                k, v = item.split("=", 1)
                parsed_config[k] = v
        gate = _Gate(
            id=gate_id,
            type=GateType(gate_type),
            description=description or f"{gate_type} gate",
            config=parsed_config,
        )
        gates = [*task.gates, gate]
        _update_task_gates(repo, task_id, gates)
        typer.echo(f"Added gate {gate_id} ({gate_type}) to {task_id}")
    except (ValueError, FileNotFoundError, KeyError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None


@task_app.command("check-gates")
def check_gates(
    task_id: str = typer.Argument(..., help="Task ID"),
) -> None:
    """Check all gates on a task."""
    task_id = _resolve_task_id(task_id)
    from ydk.core.gate_checker import GateChecker

    repo = _get_repo()
    try:
        task = repo.get_task(task_id)
        if not task.gates:
            typer.echo(f"No gates on {task_id}.")
            return
        checker = GateChecker()
        for gate in task.gates:
            status = checker.check_gate(gate)
            typer.echo(f"  {gate.id}  [{status}]  {gate.type}  {gate.description}")
    except (ValueError, FileNotFoundError, KeyError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None


@task_app.command("resolve-gate")
def resolve_gate(
    task_id: str = typer.Argument(..., help="Task ID"),
    gate_id: str = typer.Argument(..., help="Gate ID to resolve"),
) -> None:
    """Manually resolve a human gate."""
    task_id = _resolve_task_id(task_id)
    from ydk.core.gate_checker import GateChecker

    repo = _get_repo()
    try:
        task = repo.get_task(task_id)
        checker = GateChecker()
        found = False
        updated_gates: list[Gate] = []
        for gate in task.gates:
            if gate.id == gate_id:
                found = True
                updated_gates.append(checker.resolve_gate(gate))
            else:
                updated_gates.append(gate)
        if not found:
            typer.echo(f"Gate {gate_id} not found on {task_id}")
            raise typer.Exit(code=1)
        _update_task_gates(repo, task_id, updated_gates)
        typer.echo(f"Resolved gate {gate_id} on {task_id}")
    except (ValueError, FileNotFoundError, KeyError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None


def _update_task_gates(
    repo: LifecycleTaskRepository,
    task_id: str,
    gates: list[Gate],
) -> None:
    """Update gates in task frontmatter and manifest."""
    repo.update_gates(task_id, gates)


@task_app.command("add-subtask")
def add_subtask(
    task_id: str = typer.Argument(..., help="Parent task ID"),
    title: str = typer.Option(..., help="New subtask title"),
    body: str = typer.Option("", help="New subtask body"),
) -> None:
    """Create discovered subtask linked to parent."""
    task_id = _resolve_task_id(task_id)
    lc = _build_lifecycle()
    try:
        new_id = lc.discover(task_id, title, body)
        typer.echo(f"Added subtask {new_id} to {task_id}")
    except (ValueError, FileNotFoundError, KeyError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None


@task_app.command("ready")
def ready(
    ctx: typer.Context,
) -> None:
    """List all actionable tasks with satisfied dependencies, ranked by priority."""
    from rich.table import Table

    repo = _get_repo()
    tasks = repo.list_ready()

    if format_or_echo(ctx, [t.model_dump() for t in tasks]):
        return

    if not tasks:
        typer.echo("No ready tasks found.")
        return

    table = Table(title="Ready Tasks")
    table.add_column("ID", style="bold")
    table.add_column("Title")
    table.add_column("Dependents", justify="center")
    table.add_column("Deps Met", justify="center")

    for t in tasks:
        table.add_row(
            t.id,
            t.title,
            str(t.dependents_count),
            "[green]yes[/green]",
        )

    console.print(table)


@task_app.command("list")
def list_tasks(
    ctx: typer.Context,
    sprint: str | None = typer.Option(None, help="Filter by sprint/milestone"),
    epic: str | None = typer.Option(None, "--epic", help="Filter by epic ID"),
    story: str | None = typer.Option(None, "--story", help="Filter by story ID"),
    status: str | None = typer.Option(None, "--status", help="Filter by status: open|done|in-progress|all"),
) -> None:
    """List tasks with optional filters, grouped by status."""
    from ydk.repositories.factory import get_task_repository

    repo = get_task_repository()

    # Determine state filter for the repository query
    if status and status != "all":
        query_state = status
    elif sprint is not None:
        query_state = "open"
    else:
        query_state = "all"

    tasks = repo.list_tasks(state=query_state)

    # Post-filter by epic or story if requested
    if epic or story:
        filtered = []
        for t in tasks:
            try:
                detail = repo.get_task(t.id)
                if epic and detail.story_id:
                    # Check if the story belongs to the requested epic
                    try:
                        from ydk.repositories.factory import get_story_repository

                        story_repo = get_story_repository()
                        stories = story_repo.list_stories(epic_id=epic)
                        epic_story_ids = {s.id for s in stories}
                        if detail.story_id not in epic_story_ids:
                            continue
                    except Exception:
                        continue
                if story and detail.story_id != story:
                    continue
                filtered.append(t)
            except (FileNotFoundError, ValueError):
                continue
        tasks = filtered

    if format_or_echo(ctx, [t.model_dump() for t in tasks]):
        return

    if not tasks:
        typer.echo("No tasks found.")
        return

    # Group by status: open first, then in-progress, then done/closed
    status_order = {
        "open": 0,
        "in-progress": 1,
        "in-review": 2,
        "blocked-by-code": 3,
        "blocked-by-decision": 4,
        "done": 5,
        "closed": 6,
    }
    grouped: dict[str, list] = {}
    for t in tasks:
        grouped.setdefault(t.status, []).append(t)

    for group_status in sorted(grouped, key=lambda s: status_order.get(s, 99)):
        typer.echo(f"\n[{group_status}]")
        for t in grouped[group_status]:
            if t.dependencies_met:
                deps_label = "deps-met"
            else:
                # Check if any dep is truly unresolvable (not in repo)
                try:
                    detail = repo.get_task(t.id)
                    dep_ids = _extract_dep_ids(getattr(detail, "dependencies", []) or [])
                    has_unresolvable = any(not repo.task_exists(d) for d in dep_ids) if dep_ids else False
                    deps_label = "deps-UNRESOLVED" if has_unresolvable else "deps-pending"
                except (FileNotFoundError, ValueError):
                    deps_label = "deps-pending"
            typer.echo(f"  {t.id}  {t.title}  ({deps_label})")


def _extract_dep_ids(deps: list) -> list[str]:  # type: ignore[type-arg]
    """Extract task IDs from a list of dependencies (strings or Dependency objects)."""
    result: list[str] = []
    for d in deps:
        if isinstance(d, str):
            result.append(d)
        elif hasattr(d, "task_id"):
            result.append(d.task_id)
    return result


@task_app.command("validate-dag")
def validate_dag_cmd(
    label: str | None = typer.Option(None, "--label", "-l", help="Only validate tasks with this label"),
) -> None:
    """Validate task dependency graph (DAG) -- reads tasks from repository."""
    repo = _get_repo()
    summaries = repo.list_tasks(state="all")

    # Filter by label if provided
    if label:
        summaries = [s for s in summaries if hasattr(s, "labels") and label in (s.labels or [])]
        if not summaries:
            # Fallback: check via get_task for backends that don't populate labels on summary
            all_summaries = repo.list_tasks(state="all")
            filtered = []
            for s in all_summaries:
                try:
                    detail = repo.get_task(s.id)
                    task_labels = getattr(detail, "labels", None) or []
                    if label in task_labels:
                        filtered.append(s)
                except (FileNotFoundError, ValueError):
                    pass
            summaries = filtered

    if not summaries:
        typer.echo("No tasks found.")
        return

    tasks = []
    for s in summaries:
        try:
            detail = repo.get_task(s.id)
            # Use detail.id when set (local backend), fall back to
            # str(detail.number) for GitHub where id is often empty.
            effective_id = detail.id or str(detail.number)
            tasks.append(
                Task(
                    id=effective_id,
                    title=detail.title,
                    depends_on=_extract_dep_ids(getattr(detail, "dependencies", []) or []),  # ty: ignore[invalid-argument-type]
                )
            )
        except (FileNotFoundError, ValueError):
            tasks.append(Task(id=s.id, title=s.title, depends_on=[]))

    result = validate_dag(tasks)

    if not result.valid:
        if result.error:
            typer.echo(f"DAG validation FAILED \u2014 {result.error}")
        elif result.cycles:
            typer.echo("DAG validation FAILED \u2014 cycle detected.")
            for cycle in result.cycles:
                typer.echo(f"  Cycle: {cycle}")
        else:
            typer.echo("DAG validation FAILED.")
        raise typer.Exit(code=1)

    typer.echo("DAG is valid.")
    typer.echo(f"  Parallel waves: {len(result.parallel_sets)}")
    typer.echo(f"  Critical path length (dependency-only): {result.critical_path_length}")
    typer.echo(f"  Critical path (dependency-only): {' -> '.join(result.critical_path)}")

    # Run hierarchy checks if story/epic repos are available
    try:
        from ydk.core.task_validator import check_hierarchy
        from ydk.models.pm import EpicSummary as _EpicSummary
        from ydk.models.pm import StorySummary as _StorySummary
        from ydk.models.pm import TaskSummary as _TaskSummary

        # Build TaskSummary list with story_id info
        task_summaries_with_story: list[_TaskSummary] = []
        for s in summaries:
            try:
                detail = repo.get_task(s.id)
                ts = _TaskSummary(id=s.id, title=s.title, status=s.status)
                # Attach story_id dynamically for hierarchy check
                object.__setattr__(ts, "story_id", getattr(detail, "story_id", None) or "")
                task_summaries_with_story.append(ts)
            except (FileNotFoundError, ValueError):
                task_summaries_with_story.append(s)

        story_list: list[_StorySummary] = []
        epic_list: list[_EpicSummary] = []
        try:
            from ydk.repositories.factory import get_epic_repository, get_story_repository

            story_repo = get_story_repository()
            story_list = list(story_repo.list_stories())
            epic_repo = get_epic_repository()
            epic_list = [_EpicSummary(id=e.id, title=e.title) for e in epic_repo.list_epics()]  # ty: ignore[unresolved-attribute]
        except Exception:
            pass

        if story_list or epic_list:
            hierarchy_warnings = check_hierarchy(task_summaries_with_story, story_list, epic_list)
            if hierarchy_warnings:
                typer.echo("\nHierarchy warnings:")
                for w in hierarchy_warnings:
                    typer.echo(f"  - {w}")
    except Exception:
        pass


@task_app.command("component-coverage")
def component_coverage_cmd(
    exclude: list[str] = typer.Option([], "--exclude", help="Glob patterns to exclude (e.g. 'ydk:page:*')"),  # noqa: B008
    strict: bool = typer.Option(False, "--strict", help="Exit with code 1 if any uncovered components"),
) -> None:
    """Check that every component manifest is referenced by at least one task."""
    import fnmatch

    from ydk.core.task_validator import check_component_coverage

    root = Path(".")
    components_dir = root / ".ydk" / "components"
    if not components_dir.is_dir():
        typer.echo("No .ydk/components/ directory found.")
        return

    repo = _get_repo()
    summaries = repo.list_tasks(state="all")

    task_component_refs: dict[str, list[str]] = {}
    for s in summaries:
        try:
            detail = repo.get_task(s.id)
            refs = getattr(detail, "component_refs", None) or []
            if refs:
                task_component_refs[s.id] = list(refs)
        except (FileNotFoundError, ValueError):
            pass

    uncovered = check_component_coverage(components_dir, task_component_refs)

    # Filter out excluded patterns
    if exclude:
        uncovered = [c for c in uncovered if not any(fnmatch.fnmatch(c, pat) for pat in exclude)]

    if uncovered:
        typer.echo(f"Component coverage: {len(uncovered)} component(s) not referenced by any task:")
        for cid in uncovered:
            typer.echo(f"  - {cid}")
        if strict:
            raise typer.Exit(code=1)
    else:
        typer.echo("All components are referenced by at least one task.")


@task_app.command("plan-waves")
def plan_waves(
    agents: int = typer.Option(1, "--agents", help="Number of available agents"),
) -> None:
    """Display resource-constrained schedule as a table -- reads tasks from repository."""
    from rich.table import Table

    from ydk.core.scheduler import Scheduler

    repo = _get_repo()
    summaries = repo.list_tasks(state="all")

    tasks = []
    for s in summaries:
        try:
            detail = repo.get_task(s.id)
            effective_id = detail.id or str(detail.number)
            tasks.append(
                Task(
                    id=effective_id,
                    title=detail.title,
                    depends_on=_extract_dep_ids(getattr(detail, "dependencies", []) or []),  # ty: ignore[invalid-argument-type]
                )
            )
        except (FileNotFoundError, ValueError):
            tasks.append(Task(id=s.id, title=s.title, depends_on=[]))

    # Graceful handling: warn about unresolved dependencies (references to
    # tasks that don't exist in the current set).  This mirrors the safety
    # applied in validate-dag to avoid confusing schedule output.
    task_ids = {t.id for t in tasks}
    unresolved: dict[str, list[str]] = {}
    for t in tasks:
        missing = [d for d in t.blocking_dep_ids() if d not in task_ids]
        if missing:
            unresolved[t.id] = missing
    if unresolved:
        typer.echo("Warning: some dependencies reference tasks not in the current set (ignored for scheduling):")
        for tid, missing_deps in sorted(unresolved.items()):
            typer.echo(f"  {tid} depends on missing: {', '.join(missing_deps)}")
        typer.echo("")

    scheduler = Scheduler()
    result = scheduler.schedule(tasks, num_agents=agents)

    if not result.slots:
        typer.echo("No tasks to schedule.")
        return

    table = Table(title=f"Schedule ({agents} agent{'s' if agents > 1 else ''}, {result.total_waves} waves)")
    table.add_column("Wave", justify="center", style="bold")
    for a in range(agents):
        table.add_column(f"Agent {a}", justify="center")

    slot_map: dict[tuple[int, int], str] = {}
    for slot in result.slots:
        slot_map[(slot.wave, slot.agent)] = slot.task_id

    critical_set = set(result.critical_chain)
    for wave in range(result.total_waves):
        row: list[str] = [str(wave)]
        for agent in range(agents):
            tid = slot_map.get((wave, agent), "")
            if tid and tid in critical_set:
                row.append(f"[bold red]{tid}[/bold red]")
            else:
                row.append(tid)
        table.add_row(*row)

    console.print(table)
    console.print(f"\nCritical chain (resource-constrained): {' -> '.join(result.critical_chain)}")

    for agent, util in sorted(result.agent_utilization.items()):
        console.print(f"  Agent {agent}: {util:.0%} utilized")


@task_app.command()
def coverage(
    ctx: typer.Context,
    spec_dir: str | None = typer.Option(None, help="Spec directory (default: from config)"),
    milestone: str | None = typer.Option(None, help="Filter by milestone"),
    from_file: str | None = typer.Option(
        None, "--from", help="Validate coverage from batch YAML instead of live issues"
    ),
) -> None:
    """Check spec-to-story coverage."""
    from ydk.core.task_validator import check_coverage

    root = Path(".")
    # Use configured spec_location if --spec-dir not explicitly provided
    if spec_dir is None:
        try:
            from ydk.core.config import load_config as _load_cfg_cov

            cfg_cov = _load_cfg_cov()
            spec_dir = cfg_cov.project.spec_location
        except Exception:
            spec_dir = "docs/specs"
    spec_path = root / spec_dir

    # Gather spec sections: each markdown file is a "section"
    spec_sections: dict[str, list[str]] = {}
    if spec_path.is_dir():
        for md in sorted(spec_path.glob("**/*.md")):
            rel = str(md.relative_to(root))
            spec_sections[rel] = [rel]

    if not spec_sections:
        typer.echo("No spec files found.")
        return

    # --from: validate coverage from batch YAML instead of live issues
    if from_file is not None:
        from_path = Path(from_file)
        if not from_path.is_file():
            typer.echo(f"Error: file not found: {from_file}", err=True)
            raise typer.Exit(code=1)

        import yaml as _yaml

        try:
            batch_data = _yaml.safe_load(from_path.read_text(encoding="utf-8"))
        except Exception as exc:
            typer.echo(f"Error parsing YAML: {exc}", err=True)
            raise typer.Exit(code=1) from None

        if not isinstance(batch_data, dict):
            typer.echo("Error: YAML must be a mapping.", err=True)
            raise typer.Exit(code=1)

        # Extract all spec_refs from all entities in the batch YAML
        batch_refs: dict[str, set[str]] = {}
        for entity_type in ("epics", "stories", "tasks"):
            for item in batch_data.get(entity_type, []) or []:
                if not isinstance(item, dict):
                    continue
                item_id = item.get("id", "?")
                for ref in _normalize_refs(item.get("spec_refs")):
                    batch_refs.setdefault(ref, set()).add(item_id)

        # Load coverage exclusions from config
        coverage_exclude: list[str] = []
        try:
            from ydk.core.config import load_config as _load_config

            cfg = _load_config()
            coverage_exclude = cfg.task_management.coverage_exclude
        except Exception:
            pass

        uncovered = check_coverage(spec_sections, batch_refs, exclude_patterns=coverage_exclude)

        coverage_data = {
            "total_sections": len(spec_sections),
            "covered": len(spec_sections) - len(uncovered),
            "uncovered": uncovered,
            "source": str(from_path),
        }
        if format_or_echo(ctx, coverage_data):
            return

        total = len(spec_sections)
        covered = total - len(uncovered)
        typer.echo(f"Coverage (from {from_path}): {covered}/{total} spec sections have references.")
        if uncovered:
            typer.echo("\nUncovered sections:")
            for section in uncovered:
                typer.echo(f"  - {section}")
        return

    # Use repository factory to get story refs (works for any backend)
    story_refs: dict[str, set[str]] = {}
    try:
        from ydk.repositories.factory import get_story_repository

        story_repo = get_story_repository()
        stories = story_repo.list_stories()
        for s in stories:
            # For GitHub backend, parse spec_refs from issue body via parser
            sid = s.id if hasattr(s, "id") else str(getattr(s, "number", ""))
            # Try to get full story detail with spec_refs
            try:
                from ydk.repositories.github.parser import _parse_body

                # If the story has body content, parse spec_refs from it
                if hasattr(s, "description") and s.description:
                    fields, _sections = _parse_body(
                        f"**Spec refs**: {','.join(getattr(s, 'spec_refs', []))}" if hasattr(s, "spec_refs") else ""
                    )
                    refs = fields.get("spec refs", "")
                    if refs:
                        for ref in refs.split(","):
                            ref = ref.strip()
                            if ref:
                                story_refs.setdefault(ref, set()).add(sid)
            except (ImportError, AttributeError):
                pass
    except (ImportError, Exception):
        pass

    # Also read local stories if available
    stories_dir = root / ".ydk" / "stories"
    if stories_dir.is_dir():
        from ydk.repositories.local.frontmatter import parse_frontmatter

        for story_file in sorted(stories_dir.glob("S-*.md")):
            content = story_file.read_text(encoding="utf-8")
            fm, _body = parse_frontmatter(content)
            for ref in fm.get("spec_refs", []):
                story_refs.setdefault(ref, set()).add(fm.get("id", story_file.stem))

    # Load coverage exclusions from config
    coverage_exclude: list[str] = []
    try:
        from ydk.core.config import load_config as _load_config

        cfg = _load_config()
        coverage_exclude = cfg.task_management.coverage_exclude
    except Exception:
        pass

    uncovered = check_coverage(spec_sections, story_refs, exclude_patterns=coverage_exclude)

    coverage_data = {
        "total_sections": len(spec_sections),
        "covered": len(spec_sections) - len(uncovered),
        "uncovered": uncovered,
    }
    if format_or_echo(ctx, coverage_data):
        return

    total = len(spec_sections)
    covered = total - len(uncovered)
    typer.echo(f"Coverage: {covered}/{total} spec sections have stories.")
    if uncovered:
        typer.echo("\nUncovered sections:")
        for section in uncovered:
            typer.echo(f"  - {section}")


@task_app.command("analyze-complexity")
def analyze_complexity(
    ctx: typer.Context,
    task_id: str | None = typer.Option(None, "--task-id", help="Score a single task (default: all open)"),
) -> None:
    """Score task complexity (1-10) using LLM analysis."""
    from rich.table import Table

    from ydk.core.complexity_scorer import ComplexityScorer

    repo = _get_repo()

    llm_provider = _get_llm_provider()
    scorer = ComplexityScorer(llm_provider=llm_provider)

    scores: list[ComplexityScore] = []
    if task_id:
        task = repo.get_task(task_id)
        scores.append(scorer.score_task(task))
    else:
        summaries = repo.list_tasks(state="open")
        tasks = [repo.get_task(s.id) for s in summaries]
        scores = scorer.score_tasks(tasks)

    if format_or_echo(ctx, [s.model_dump() for s in scores]):
        return

    if not scores:
        typer.echo("No tasks to analyze.")
        return

    table = Table(title="Task Complexity Analysis")
    table.add_column("Task ID", style="bold")
    table.add_column("Title")
    table.add_column("Score", justify="center")
    table.add_column("Reasoning")

    for s in scores:
        if s.score <= 3:
            score_str = f"[green]{s.score}[/green]"
        elif s.score <= 6:
            score_str = f"[yellow]{s.score}[/yellow]"
        else:
            score_str = f"[red]{s.score}[/red]"

        title = s.task_id
        try:
            detail = repo.get_task(s.task_id)
            title = detail.title
        except (FileNotFoundError, ValueError):
            pass

        table.add_row(s.task_id, title, score_str, s.reasoning)

    console.print(table)


@task_app.command("archive-done")
def archive_done(
    task_id: str | None = typer.Option(None, "--task-id", help="Compact a specific task"),
    all_done: bool = typer.Option(False, "--all-done", help="Compact all done tasks"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be compacted"),
) -> None:
    """Archive completed tasks into context-efficient summaries."""
    repo = _get_repo()

    if task_id:
        if dry_run:
            task = repo.get_task(task_id)
            if task.status in {"done", "closed"}:
                typer.echo(f"Would compact: {task_id} ({task.title})")
            else:
                typer.echo(f"Task {task_id} not compactable (status={task.status})")
            return

        try:
            repo.compact_task(task_id)
            typer.echo(f"Compacted task {task_id}")
        except (ValueError, FileNotFoundError) as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from None
        return

    if all_done:
        compacted_ids = repo.compact_all_done(dry_run=dry_run)
        if not compacted_ids:
            typer.echo("No tasks to compact.")
            return
        verb = "Would compact" if dry_run else "Compacted"
        typer.echo(f"{verb} {len(compacted_ids)} task(s):")
        for tid in compacted_ids:
            typer.echo(f"  {tid}")
        return

    typer.echo("Specify --task-id or --all-done.", err=True)
    raise typer.Exit(code=1)


@task_app.command("create-epic")
def create_epic(
    ctx: typer.Context,
    title: str = typer.Option(..., "--title"),
    description: str = typer.Option("", "--description"),
    release: str = typer.Option("", "--release"),
    spec_refs: list[str] = typer.Option([], "--spec-refs"),  # noqa: B008
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate and show what would be created without calling the API"
    ),
) -> None:
    """Create a new epic."""
    if dry_run:
        console.print("[yellow]Dry run -- no epic will be created[/yellow]")
        console.print(f"  Title: {title}")
        if description:
            console.print(f"  Description: {description}")
        if spec_refs:
            console.print(f"  Spec refs: {spec_refs}")
        raise typer.Exit(0)

    from ydk.models.pm import EpicCreate
    from ydk.repositories.factory import get_epic_repository

    repo = get_epic_repository()
    epic = EpicCreate(title=title, description=description, release=release, spec_refs=spec_refs)
    detail = repo.create_epic(epic)

    if not format_or_echo(ctx, detail):
        epic_label = detail.id or f"E-{detail.number:03d}"
        console.print(f"[green]Created epic {epic_label}:[/green] {detail.title}")


@task_app.command("create-story")
def create_story(
    ctx: typer.Context,
    title: str = typer.Option(..., "--title"),
    epic_id: str = typer.Option(..., "--epic"),
    description: str = typer.Option("", "--description"),
    spec_refs: list[str] = typer.Option([], "--spec-refs"),  # noqa: B008
    component_refs: list[str] = typer.Option([], "--component-refs"),  # noqa: B008
    acceptance: list[str] = typer.Option([], "--acceptance"),  # noqa: B008
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate and show what would be created without calling the API"
    ),
) -> None:
    """Create a new story."""
    if dry_run:
        console.print("[yellow]Dry run -- no story will be created[/yellow]")
        console.print(f"  Title: {title}")
        console.print(f"  Epic: {epic_id}")
        if spec_refs:
            console.print(f"  Spec refs: {spec_refs}")
        if component_refs:
            console.print(f"  Component refs: {component_refs}")
        raise typer.Exit(0)

    from ydk.models.pm import StoryCreate
    from ydk.repositories.factory import get_story_repository

    # Validate component_refs and spec_refs at creation time
    project_root = Path(".")
    if component_refs:
        _validate_component_refs_cli(component_refs, project_root)
    if spec_refs:
        _validate_spec_refs_cli(spec_refs, project_root)

    # Warn on missing acceptance criteria
    _warn_missing_acceptance(list(acceptance), ctx)

    repo = get_story_repository()
    story = StoryCreate(
        title=title,
        epic_id=epic_id,
        description=description,
        spec_refs=spec_refs,
        component_refs=component_refs,
        acceptance_criteria=list(acceptance),  # type: ignore[arg-type]
    )
    detail = repo.create_story(story)

    if not format_or_echo(ctx, detail):
        story_label = detail.id or f"S-{detail.number:03d}"
        console.print(f"[green]Created story {story_label}:[/green] {detail.title}")


@task_app.command("quick")
def quick(
    ctx: typer.Context,
    description: str = typer.Argument(..., help="Short description of the change"),
) -> None:
    """Set up a lightweight workspace for a small change."""
    from ydk.core.quickdev import QuickDevSetup

    setup = QuickDevSetup()
    result = setup.setup(description, Path.cwd())

    if format_or_echo(ctx, result.model_dump()):
        return

    typer.echo("\\n--- Quick Dev Setup ---")
    typer.echo(f"Task:   {result.task_id}")
    typer.echo(f"Branch: {result.branch}")
    typer.echo(f"Description: {result.description}")
    if result.components:
        typer.echo(f"Relevant components: {', '.join(result.components)}")
    typer.echo(f"Testing: {result.testing_guidance}")
    typer.echo("\\nWorkspace is ready. Start coding!")


@task_app.command("tdd")
def tdd(
    task_id: str = typer.Argument(..., help="Task ID"),
    stage: str = typer.Option(..., "--stage", help="TDD phase: red|green|refactor"),
) -> None:
    """Set TDD phase on task (stored in frontmatter)."""
    valid_stages = {"red", "green", "refactor"}
    if stage not in valid_stages:
        stages_str = ", ".join(sorted(valid_stages))
        typer.echo(f"Error: stage must be one of: {stages_str}", err=True)
        raise typer.Exit(code=1)

    repo = _get_repo()
    try:
        repo.get_task(task_id)
        repo.update_frontmatter(task_id, {"tdd_stage": stage})
        typer.echo(f"Task {task_id} TDD stage set to: {stage}")
    except (ValueError, FileNotFoundError, KeyError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None


def _get_llm_provider() -> LLMProvider | None:
    """Try to construct an LLM provider from project config.

    Uses ``cfg.aws`` for credentials and ``cfg.ai`` for model selection.
    Falls back to ``None`` (default score) when boto3 is unavailable or
    no AWS profile is configured.
    """
    try:
        import boto3

        from ydk.core.config import load_config

        cfg = load_config()

        session_kwargs: dict[str, str] = {}
        if cfg.aws.profile:
            session_kwargs["profile_name"] = cfg.aws.profile
        if cfg.aws.region:
            session_kwargs["region_name"] = cfg.aws.region

        session = boto3.Session(**session_kwargs)
        bedrock = session.client("bedrock-runtime")

        model_id = cfg.ai.model_tiers.get("fast", "us.anthropic.claude-sonnet-4-20250514-v1:0")

        return _BedrockLLMProvider(client=bedrock, model_id=model_id)
    except Exception:
        return None


@task_app.command("review-comments")
def review_comments(
    task_id: str = typer.Argument(..., help="Task ID to fetch review comments for"),
) -> None:
    """Fetch unresolved PR review comments for a task."""
    task_id = _resolve_task_id(task_id)
    comments = _fetch_review_comments(task_id)
    if not comments:
        typer.echo(f"No review comments found for {task_id}.")
        return

    unresolved = [c for c in comments if not c.get("resolved", False)]
    resolved = [c for c in comments if c.get("resolved", False)]

    if unresolved:
        typer.echo(f"\n{len(unresolved)} unresolved review comment(s):")
        for i, c in enumerate(unresolved, 1):
            location = c.get("path", "General")
            if c.get("line"):
                location = f"{location}:{c['line']}"
            author = c.get("author", "unknown")
            body = str(c.get("body", "")).split("\n")[0][:80]
            typer.echo(f'  {i}. {location} — "{body}" ({author})')

    if resolved:
        typer.echo(f"\n{len(resolved)} resolved review comment(s).")


def _fetch_review_comments(task_id: str) -> list[dict[str, object]]:
    """Fetch PR review comments for a task branch via ``gh`` CLI.

    Returns a list of dicts with keys: path, line, body, author, resolved.
    """
    import json
    import subprocess

    # Find PR for this task's branch pattern
    find_pr_cmd = [
        "gh",
        "pr",
        "list",
        "--head",
        f"task/{task_id}",
        "--json",
        "number,url",
        "--state",
        "all",
    ]
    result = subprocess.run(find_pr_cmd, capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        return []

    try:
        prs = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    if not prs:
        return []

    pr_number = prs[0]["number"]

    # Fetch review comments via the reviews API
    comments_cmd = [
        "gh",
        "api",
        f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/comments",
        "--jq",
        ".",
    ]
    result = subprocess.run(comments_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return []

    try:
        raw_comments = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    parsed: list[dict[str, object]] = [
        {
            "path": c.get("path", ""),
            "line": c.get("line") or c.get("original_line"),
            "body": c.get("body", ""),
            "author": c.get("user", {}).get("login", "unknown"),
            "resolved": False,  # Line comments from this endpoint are unresolved by default
        }
        for c in raw_comments
    ]

    # Also fetch review threads for resolution status
    threads_cmd = [
        "gh",
        "pr",
        "view",
        str(pr_number),
        "--json",
        "reviewThreads",
    ]
    result = subprocess.run(threads_cmd, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        try:
            data = json.loads(result.stdout)
            threads = data.get("reviewThreads", [])
            for thread in threads:
                is_resolved = thread.get("isResolved", False)
                for comment in thread.get("comments", []):
                    # Match by body to update resolution status
                    body = comment.get("body", "")
                    for p in parsed:
                        if p["body"] == body:
                            p["resolved"] = is_resolved
        except json.JSONDecodeError:
            pass

    return parsed


@task_app.command("scaffold-batch")
def scaffold_batch(
    output: str = typer.Option("batch-tasks.yaml", "--output", "-o", help="Output file path"),
) -> None:
    """Generate a batch YAML template from existing TODOs, grouped by service."""
    import re as _re

    import yaml as _yaml

    from ydk.core.todo_manager import TodoManager

    output_path = Path(output)
    mgr = TodoManager(Path.cwd())
    items = mgr.list_todos(status="open")

    if not items:
        console.print("[yellow]No open TODOs found.[/yellow]")
        return

    # Group TODOs by service name extracted from file path
    # Pattern: app/core/services/{name}/service.py or similar
    service_groups: dict[str, list] = {}
    for todo in items:
        # Try to extract service name from path
        match = _re.search(r"(?:services|adapters)/([^/]+)/", todo.file)
        svc_name = match.group(1) if match else "misc"
        service_groups.setdefault(svc_name, []).append(todo)

    # Build YAML structure
    epics = [
        {
            "id": "E-001",
            "title": "Implement Business Logic",
            "description": "Auto-generated from TODO inventory",
        }
    ]

    stories = []
    tasks = []
    story_idx = 1
    task_idx = 1

    for svc_name, todos in sorted(service_groups.items()):
        # Convert snake_case to PascalCase for display
        pascal = "".join(w.capitalize() for w in svc_name.split("_"))
        story_id = f"S-{story_idx:03d}"
        stories.append(
            {
                "id": story_id,
                "title": f"Implement {pascal}",
                "epic": "E-001",
                "spec_refs": [],
            }
        )

        task_id = f"T-{task_idx:03d}"
        tasks.append(
            {
                "id": task_id,
                "title": f"Implement {pascal} business logic",
                "story": story_id,
                "component_refs": [f"ydk:contract:{svc_name}/{pascal}Service"],
                "todos": [t.id for t in todos],
                "acceptance_criteria": [
                    f"All {pascal} methods implemented",
                    "Unit tests pass",
                ],
            }
        )

        story_idx += 1
        task_idx += 1

    # Add final verification task that depends on all other tasks
    all_task_ids = [t["id"] for t in tasks]
    final_task = {
        "id": "T-FINAL",
        "title": "Final verification: all tests pass, zero xfail",
        "story": stories[0]["id"] if stories else "S-001",
        "depends_on": all_task_ids,
        "acceptance_criteria": [
            "Zero @pytest.mark.xfail in test suite",
            "Zero NotImplementedError in services",
            "All E2E tests pass",
            "Full ruff + ty clean",
        ],
        "test_strategy": "Run full test suite with --strict-markers, verify zero xfail remaining",
    }
    tasks.append(final_task)

    batch = {
        "epics": epics,
        "stories": stories,
        "tasks": tasks,
    }

    output_path.write_text(_yaml.dump(batch, default_flow_style=False, sort_keys=False))
    console.print(f"[green]Batch YAML written to {output_path}[/green]")
    console.print(f"  {len(epics)} epic(s), {len(stories)} story(ies), {len(tasks)} task(s)")
    console.print(f"  Covering {len(items)} TODO(s)")
    console.print("  [bold]T-FINAL[/bold] added — depends on all tasks, verifies zero xfail")


class _BedrockLLMProvider:
    """Minimal LLM provider backed by AWS Bedrock ``converse`` API."""

    def __init__(self, client: object, model_id: str) -> None:
        self._client: object = client
        self._model_id = model_id

    def invoke(self, prompt: str) -> str:
        """Send *prompt* to Bedrock and return the text response."""
        import json

        response = self._client.invoke_model(  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]
            modelId=self._model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(
                {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                }
            ),
        )
        result = json.loads(response["body"].read())
        return result["content"][0]["text"]  # type: ignore[no-any-return]

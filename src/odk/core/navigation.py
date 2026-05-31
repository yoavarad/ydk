"""Intelligent navigation — detect project stage and recommend next action."""

from __future__ import annotations

from typing import TYPE_CHECKING

from odk.models.navigation import ComponentCoverage, NavigationStatus, ProjectStage

if TYPE_CHECKING:
    from pathlib import Path


def _count_files(directory: Path, pattern: str = "*.md") -> int:
    """Count files matching a pattern in a directory."""
    if not directory.is_dir():
        return 0
    return len(list(directory.glob(pattern)))


def _count_yaml_files(directory: Path) -> int:
    """Count YAML files in a directory."""
    if not directory.is_dir():
        return 0
    return len(list(directory.glob("*.yaml"))) + len(list(directory.glob("*.yml")))


def _scan_task_statuses(tasks_dir: Path) -> dict[str, int]:
    """Scan task files and count by status."""
    counts: dict[str, int] = {}
    if not tasks_dir.is_dir():
        return counts

    for task_file in tasks_dir.glob("*.md"):
        content = task_file.read_text(encoding="utf-8")
        status = "open"
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("status:"):
                status = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                break
        counts[status] = counts.get(status, 0) + 1

    return counts


def _get_component_coverage(
    components_dir: Path,
    tasks_dir: Path,
) -> ComponentCoverage | None:
    """Calculate component coverage if components directory exists."""
    if not components_dir.is_dir():
        return None

    all_components: set[str] = set()
    for f in components_dir.rglob("*.yaml"):
        all_components.add(f.stem)
    for f in components_dir.rglob("*.yml"):
        all_components.add(f.stem)

    if not all_components:
        return None

    # Scan tasks for component references
    referenced: set[str] = set()
    if tasks_dir.is_dir():
        for task_file in tasks_dir.glob("*.md"):
            content = task_file.read_text(encoding="utf-8")
            for comp in all_components:
                if comp in content:
                    referenced.add(comp)

    orphaned = all_components - referenced
    return ComponentCoverage(
        total=len(all_components),
        referenced_by_tasks=len(referenced),
        orphaned=len(orphaned),
    )


def detect_stage(odk_root: Path) -> ProjectStage:
    """Detect which ODK stage the project is in based on artifacts present."""
    if not odk_root.is_dir():
        return ProjectStage.EMPTY

    specs_dir = odk_root / "specs"
    tasks_dir = odk_root / "tasks"

    has_specs = specs_dir.is_dir() and any(specs_dir.glob("*.md"))
    has_tasks = tasks_dir.is_dir() and any(tasks_dir.glob("*.md"))

    if not has_specs and not has_tasks:
        return ProjectStage.INITIALIZED

    if has_specs and not has_tasks:
        return ProjectStage.SPECIFIED

    if has_tasks:
        statuses = _scan_task_statuses(tasks_dir)
        in_review = statuses.get("in-review", 0)
        in_progress = statuses.get("in-progress", 0)
        done = statuses.get("done", 0)

        if in_review > 0:
            return ProjectStage.REVIEWING
        if in_progress > 0 or done > 0:
            return ProjectStage.IN_PROGRESS
        return ProjectStage.TASKED

    return ProjectStage.INITIALIZED


def recommend_next_action(stage: ProjectStage, task_counts: dict[str, int]) -> str:
    """Recommend the next action based on stage and task statuses."""
    if stage == ProjectStage.EMPTY:
        return "Run `odk init` to initialize the project."
    if stage == ProjectStage.INITIALIZED:
        return "Create specs with `odk spec create` to define your project."
    if stage == ProjectStage.SPECIFIED:
        return "Specs exist but no tasks. Run `odk task create` to break specs into tasks."
    if stage == ProjectStage.TASKED:
        open_count = task_counts.get("open", 0)
        if open_count > 0:
            return f"{open_count} task(s) ready. Run `odk task ready` to pick the next one."
        return "All tasks started. Monitor progress with `odk status`."
    if stage == ProjectStage.IN_PROGRESS:
        in_progress = task_counts.get("in-progress", 0)
        blocked = sum(v for k, v in task_counts.items() if k.startswith("blocked"))
        if blocked > 0:
            return f"{blocked} task(s) blocked. Resolve blockers before continuing."
        return f"{in_progress} task(s) in progress. Complete them with `odk task done <id>`."
    if stage == ProjectStage.REVIEWING:
        return "Tasks are in review. Merge PRs and close tasks."
    return "Check project status."


def scan_project(project_root: Path) -> NavigationStatus:
    """Scan the project and produce a full navigation status."""
    odk_root = project_root / ".odk"

    stage = detect_stage(odk_root)

    specs_dir = odk_root / "specs"
    adrs_dir = odk_root / "adrs"
    tasks_dir = odk_root / "tasks"
    components_dir = odk_root / "components"
    stories_dir = odk_root / "stories"
    epics_dir = odk_root / "epics"

    spec_count = _count_files(specs_dir)
    adr_count = _count_files(adrs_dir)
    task_counts = _scan_task_statuses(tasks_dir)
    story_count = _count_files(stories_dir)
    epic_count = _count_files(epics_dir)
    component_count = _count_yaml_files(components_dir)
    component_coverage = _get_component_coverage(components_dir, tasks_dir)

    next_action = recommend_next_action(stage, task_counts)

    return NavigationStatus(
        stage=stage,
        next_action=next_action,
        spec_count=spec_count,
        adr_count=adr_count,
        component_count=component_count,
        task_counts=task_counts,
        story_count=story_count,
        epic_count=epic_count,
        component_coverage=component_coverage,
    )

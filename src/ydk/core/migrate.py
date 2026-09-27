"""Migrate local epics/stories/tasks to GitHub issues (``ydk task migrate --to github``).

Items are created in dependency order (epics, stories, then tasks sorted so
blocking-or-not dependencies come first). Parent links and dependencies are
rewritten to ``#N``; statuses, gates, TDD stage and labels are carried over.
The ``local-id -> #N`` map is merged into ``batch-mapping.json`` after each
creation, so the shared resolver (``ydk.core.task_ref``) accepts old IDs and
a re-run skips everything already mapped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ydk.models.pm import (
    AcceptanceCriterion,
    Dependency,
    EpicCreate,
    EpicDetail,
    StoryCreate,
    StoryDetail,
    TaskCreate,
    TaskDetail,
)
from ydk.repositories.local.epics import LocalEpicRepository
from ydk.repositories.local.frontmatter import parse_frontmatter
from ydk.repositories.local.stories import LocalStoryRepository
from ydk.repositories.local.tasks import LocalTaskRepository

if TYPE_CHECKING:
    from pathlib import Path

# Sidecar next to the mapping file: IDs whose issue exists but whose follow-up
# calls (status, labels, TDD stage, deps) have not all succeeded yet.
PENDING_FILE_NAME = "migrate-pending.json"

# Local statuses that close the GitHub issue; other non-open statuses become labels.
_CLOSED_STATUSES = frozenset({"done", "closed"})


class _EpicTarget(Protocol):
    def create_epic(self, epic: EpicCreate) -> EpicDetail: ...


class _StoryTarget(Protocol):
    def create_story(self, story: StoryCreate) -> StoryDetail: ...


class _TaskTarget(Protocol):
    def create_task(self, task: TaskCreate) -> TaskDetail: ...
    def update_status(self, issue_number: str, status: str) -> None: ...
    def add_label(self, task_id: str, label: str) -> None: ...
    def update_frontmatter(self, task_id: str, fields: dict[str, object]) -> None: ...


@dataclass(frozen=True)
class PlanItem:
    """One entity in the migration plan."""

    kind: str  # "epic" | "story" | "task"
    local_id: str
    title: str
    action: str  # "create" | "skip"
    target: str = ""  # "#N" once known (from mapping or after creation)


def load_mapping(mapping_file: Path) -> dict[str, str]:
    """Read ``batch-mapping.json``; missing or malformed files yield ``{}``."""
    try:
        data = json.loads(mapping_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _save_mapping(mapping_file: Path, mapping: dict[str, str]) -> None:
    mapping_file.parent.mkdir(parents=True, exist_ok=True)
    mapping_file.write_text(json.dumps(mapping, indent=2), encoding="utf-8")


def _read_entity(path: Path) -> tuple[dict, str]:
    """Return (frontmatter, description) of a local epic/story markdown file."""
    if not path.exists():
        return {}, ""
    fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    description: list[str] = []
    in_section = False
    for line in body.splitlines():
        if line.strip() == "## Description":
            in_section = True
            continue
        if in_section and line.strip().startswith("## "):
            break
        if in_section:
            description.append(line)
    return fm, "\n".join(description).strip()


def _acceptance(raw: list[dict[str, object] | str] | None) -> list[str | AcceptanceCriterion]:
    items: list[str | AcceptanceCriterion] = []
    for ac in raw or []:
        if isinstance(ac, dict):
            items.append(AcceptanceCriterion(text=str(ac.get("text", "")), done=bool(ac.get("done", False))))
        else:
            items.append(str(ac))
    return items


def _dep_id(dep: str | Dependency) -> str:
    return dep.task_id if isinstance(dep, Dependency) else str(dep)


def _order_tasks(tasks: list[TaskDetail]) -> list[TaskDetail]:
    """Stable topological order: dependencies (any type) before dependents; cycles keep source order."""
    by_id = {t.id: t for t in tasks}
    ordered: list[TaskDetail] = []
    placed: set[str] = set()
    remaining = list(tasks)
    while remaining:
        ready = [t for t in remaining if all(_dep_id(d) in placed or _dep_id(d) not in by_id for d in t.dependencies)]
        batch = ready or remaining[:1]  # break a cycle with the first remaining task
        for t in batch:
            ordered.append(t)
            placed.add(t.id)
        remaining = [t for t in remaining if t.id not in placed]
    return ordered


def _load_source(root: Path) -> tuple[list[tuple[dict, str, str]], list[tuple[dict, str, str]], list[TaskDetail]]:
    """Read local epics, stories (as (frontmatter, description, status)) and full task details."""
    epics = [
        (*_read_entity(root / "epics" / f"{e.id}.md"), e.status) for e in LocalEpicRepository(root).list_epics("all")
    ]
    stories = [
        (*_read_entity(root / "stories" / f"{s.id}.md"), s.status) for s in LocalStoryRepository(root).list_stories()
    ]
    task_repo = LocalTaskRepository(root)
    tasks: list[TaskDetail] = []
    for summary in task_repo.list_tasks(state="all"):
        detail = task_repo.get_task(summary.id)
        fm, _ = parse_frontmatter((root / "tasks" / f"{summary.id}.md").read_text(encoding="utf-8"))
        detail.tdd_stage = fm.get("tdd_stage") or None
        tasks.append(detail)
    return epics, stories, _order_tasks(tasks)


def _number(ref: str) -> str:
    return ref.lstrip("#")


def _resolve_deps(deps: list[str | Dependency], mapping: dict[str, str]) -> list[str | Dependency]:
    """Rewrite dependency IDs through *mapping*, keeping each dependency's type."""
    return [
        Dependency(task_id=mapping.get(d.task_id, d.task_id), type=d.type)
        if isinstance(d, Dependency)
        else mapping.get(str(d), str(d))
        for d in deps
    ]


def migrate_to_github(
    source_root: Path,
    mapping_file: Path,
    *,
    epic_repo: _EpicTarget,
    story_repo: _StoryTarget,
    task_repo: _TaskTarget,
    dry_run: bool = False,
) -> list[PlanItem]:
    """Migrate the local repositories under *source_root* to the GitHub target repos.

    Args:
        source_root: The local ``.ydk`` root holding ``epics/``, ``stories/``, ``tasks/``.
        mapping_file: ``batch-mapping.json`` path; read for skips, merged and rewritten.
        epic_repo: Target epic repository (GitHub).
        story_repo: Target story repository (GitHub).
        task_repo: Target task repository (GitHub). Also closes/labels epic and story
            issues, since GitHub issue state operations are type-agnostic.
        dry_run: Return the plan without calling any target repository.

    Returns:
        The plan, in creation order. ``action`` is ``create``, ``skip`` (already
        mapped) or ``finalize`` (created by an interrupted run; follow-up calls
        such as status, labels, TDD stage and deps are re-applied).
    """
    mapping = load_mapping(mapping_file)
    pending_file = mapping_file.with_name(PENDING_FILE_NAME)
    pending = load_mapping(pending_file)  # local_id -> "#N", written before batch-mapping.json
    lagging = {k: v for k, v in pending.items() if mapping.get(k) != v}
    epics, stories, tasks = _load_source(source_root)

    def ref(local_id: str | None) -> str | None:
        return mapping.get(local_id, local_id) if local_id else None

    def plan_item(kind: str, local_id: str, title: str) -> PlanItem:
        if local_id in pending:
            return PlanItem(kind, local_id, title, "finalize", pending[local_id])
        if local_id in mapping:
            return PlanItem(kind, local_id, title, "skip", mapping[local_id])
        return PlanItem(kind, local_id, title, "create")

    if dry_run:
        return [
            *(plan_item("epic", str(fm.get("id")), str(fm.get("title", ""))) for fm, _, _ in epics),
            *(plan_item("story", str(fm.get("id")), str(fm.get("title", ""))) for fm, _, _ in stories),
            *(plan_item("task", t.id, t.title) for t in tasks),
        ]

    if lagging:  # a crash hit between the pending-file and mapping writes
        mapping.update(lagging)
        _save_mapping(mapping_file, mapping)
    plan: list[PlanItem] = []

    def save_pending() -> None:
        if not pending:
            pending_file.unlink(missing_ok=True)
            return
        _save_mapping(pending_file, pending)

    def created(item: PlanItem, number: int) -> PlanItem:
        """Persist the new issue number before any follow-up call, so a crash never re-creates it."""
        mapping[item.local_id] = pending[item.local_id] = f"#{number}"
        save_pending()  # first: a crash before the mapping write still resumes as "finalize"
        _save_mapping(mapping_file, mapping)
        return PlanItem(item.kind, item.local_id, item.title, "create", f"#{number}")

    def apply_status(number: str, status: str) -> None:
        if status in _CLOSED_STATUSES:
            task_repo.update_status(number, "done")
        elif status and status != "open":
            task_repo.update_status(number, status)

    def finished(item: PlanItem) -> None:
        pending.pop(item.local_id, None)
        save_pending()
        plan.append(item)

    for fm, description, status in epics:
        item = plan_item("epic", str(fm.get("id")), str(fm.get("title", "")))
        if item.action == "skip":
            plan.append(item)
            continue
        if item.action == "create":
            detail = epic_repo.create_epic(
                EpicCreate(
                    title=item.title,
                    description=description,
                    release=str(fm.get("release") or ""),
                    spec_refs=list(fm.get("spec_refs") or []),
                )
            )
            item = created(item, detail.number)
        apply_status(_number(item.target), status)
        finished(item)

    for fm, description, status in stories:
        item = plan_item("story", str(fm.get("id")), str(fm.get("title", "")))
        if item.action == "skip":
            plan.append(item)
            continue
        if item.action == "create":
            detail = story_repo.create_story(
                StoryCreate(
                    title=item.title,
                    epic_id=ref(fm.get("epic")),
                    description=description,
                    spec_refs=list(fm.get("spec_refs") or []),
                    acceptance_criteria=_acceptance(fm.get("acceptance_criteria")),
                )
            )
            item = created(item, detail.number)
        apply_status(_number(item.target), status)
        finished(item)

    local_task_ids = {t.id for t in tasks}
    # Tasks whose deps must be rewritten once every task has an issue number:
    # cycle members created while a local dep was still unmapped, and resumed tasks.
    deferred: list[tuple[PlanItem, TaskDetail]] = []
    for task in tasks:
        item = plan_item("task", task.id, task.title)
        if item.action == "skip":
            plan.append(item)
            continue
        resume = item.action == "finalize"
        if not resume:
            detail = task_repo.create_task(
                TaskCreate(
                    title=task.title,
                    story_id=ref(task.story_id),
                    spec_refs=task.spec_refs,
                    component_refs=task.component_refs,
                    dependencies=_resolve_deps(task.dependencies, mapping),
                    test_strategy=task.test_strategy,
                    description=task.description,
                    acceptance_criteria=task.acceptance_criteria,
                    gates=task.gates,
                )
            )
            item = created(item, detail.number)
        number = _number(item.target)
        for label in task.labels:
            task_repo.add_label(number, label)
        if task.tdd_stage:
            task_repo.update_frontmatter(number, {"tdd_stage": task.tdd_stage})
        apply_status(number, task.status)
        local_deps = [_dep_id(d) for d in task.dependencies if _dep_id(d) in local_task_ids]
        if (resume and local_deps) or any(dep not in mapping for dep in local_deps):
            deferred.append((item, task))
        else:
            finished(item)

    for item, task in deferred:
        task_repo.update_frontmatter(_number(item.target), {"dependencies": _resolve_deps(task.dependencies, mapping)})
        finished(item)
    return plan

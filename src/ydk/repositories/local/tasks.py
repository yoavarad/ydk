"""Local file-based task repository implementation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ydk.core.compaction import TaskCompactor
from ydk.models.gate import Gate, GateStatus, GateType
from ydk.models.pm import (
    BLOCKING_DEPENDENCY_TYPES,
    AcceptanceCriterion,
    Dependency,
    DependencyStatus,
    DependencyType,
    TaskCreate,
    TaskDetail,
    TaskSummary,
)
from ydk.repositories.local.frontmatter import (
    append_comment,
    parse_frontmatter,
    render_frontmatter,
    update_file_status,
)
from ydk.repositories.local.manifest import Manifest, parse_number_from_id

if TYPE_CHECKING:
    from pathlib import Path

    from ydk.models.compaction import CompactedTask


class LocalTaskRepository:
    """Store tasks as markdown files with YAML frontmatter + manifest index.

    Local IDs are formatted as T-NNN; the numeric portion maps to ``number``.
    """

    def __init__(self, tasks_root: Path) -> None:
        """tasks_root is the .ydk/tasks/ directory."""
        self._root = tasks_root
        self._tasks_dir = tasks_root / "tasks"
        self._manifest = Manifest(tasks_root)

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def create_task(self, task: TaskCreate) -> TaskDetail:
        """Generate ID, write T-NNN.md, update manifest. Returns TaskDetail."""
        task_id = self._manifest.next_task_id()
        number = parse_number_from_id(task_id)
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        ac_dicts: list[dict[str, object]] = []
        for ac in task.acceptance_criteria:
            if isinstance(ac, AcceptanceCriterion):
                ac_dicts.append({"text": ac.text, "done": ac.done})
            else:
                ac_dicts.append({"text": str(ac), "done": False})

        frontmatter: dict[str, object] = {
            "id": task_id,
            "title": task.title,
            "story": task.story_id,
            "status": "open",
            "assignee": None,
            "labels": [*task.labels],
            "dependencies": _serialize_deps(task.dependencies),
            "spec_refs": [*task.spec_refs],
            "component_refs": [*task.component_refs],
            "test_strategy": task.test_strategy,
            "acceptance_criteria": ac_dicts,
            "milestone": task.milestone,
            "complexity": task.complexity,
            "gates": _serialize_gates(task.gates),
            "created": now,
            "updated": now,
        }

        body = f"## Description\n\n{task.description}\n\n## Activity Log\n"

        self._tasks_dir.mkdir(parents=True, exist_ok=True)
        file_path = self._tasks_dir / f"{task_id}.md"
        file_path.write_text(render_frontmatter(frontmatter, body), encoding="utf-8")

        # Update manifest
        data = self._manifest.load()
        manifest_entry: dict[str, object] = {
            "title": task.title,
            "story": task.story_id,
            "status": "open",
            "dependencies": _serialize_deps(task.dependencies),
            "component_refs": [*task.component_refs],
        }
        if task.complexity is not None:
            manifest_entry["complexity"] = task.complexity
        if task.gates:
            manifest_entry["gates"] = _serialize_gates(task.gates)
        data["tasks"][task_id] = manifest_entry
        # Also update story's task list if story exists
        story_id = task.story_id
        if story_id and story_id in data.get("stories", {}):
            story = data["stories"][story_id]
            if task_id not in story.get("tasks", []):
                story.setdefault("tasks", []).append(task_id)
        self._manifest.save(data)

        return TaskDetail(
            number=number,
            id=task_id,
            title=task.title,
            story_id=task.story_id,
            spec_refs=[*task.spec_refs],
            component_refs=[*task.component_refs],
            dependencies=[*task.dependencies],
            test_strategy=task.test_strategy,
            description=task.description,
            acceptance_criteria=[*task.acceptance_criteria],
            labels=[*task.labels],
            status="open",
            complexity=task.complexity,
            url="",
            gates=[*task.gates],
        )

    def get_task(self, task_id: str) -> TaskDetail:
        """Read file, parse frontmatter + body -> TaskDetail."""
        file_path = self._tasks_dir / f"{task_id}.md"
        if not file_path.exists():
            raise FileNotFoundError(f"Task {task_id} not found")
        content = file_path.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)

        # Extract description from body
        description = _extract_section(body, "Description")

        # Parse acceptance criteria from frontmatter
        raw_ac = fm.get("acceptance_criteria", [])
        acceptance_criteria: list[str | AcceptanceCriterion] = []
        for ac in raw_ac:
            if isinstance(ac, dict):
                acceptance_criteria.append(AcceptanceCriterion(text=ac.get("text", ""), done=ac.get("done", False)))
            else:
                acceptance_criteria.append(AcceptanceCriterion(text=str(ac)))

        gates = _deserialize_gates(fm.get("gates", []))

        number = parse_number_from_id(task_id)

        return TaskDetail(
            number=number,
            id=fm.get("id", task_id),
            title=fm.get("title", ""),
            story_id=fm.get("story"),
            spec_refs=fm.get("spec_refs", []),
            component_refs=fm.get("component_refs", []),
            dependencies=_deserialize_deps(fm.get("dependencies", [])),
            description=description,
            acceptance_criteria=acceptance_criteria,
            test_strategy=fm.get("test_strategy", ""),
            status=fm.get("status", "open"),
            assignee=fm.get("assignee"),
            labels=fm.get("labels", []),
            complexity=fm.get("complexity"),
            complexity_reasoning=fm.get("complexity_reasoning"),
            url="",
            gates=gates,
        )

    def task_exists(self, task_id: str) -> bool:
        """Check if a task ID exists in the local repository."""
        file_path = self._tasks_dir / f"{task_id}.md"
        return file_path.exists()

    def list_tasks(
        self,
        state: str = "open",
    ) -> list[TaskSummary]:
        """Read manifest (fast, no file parsing). Filter by state."""
        data = self._manifest.load()
        results: list[TaskSummary] = []
        for tid, info in data.get("tasks", {}).items():
            if state != "all" and info.get("status", "open") != state:
                continue
            raw_deps = info.get("dependencies", [])
            blocking_ids = _extract_blocking_dep_ids(raw_deps)
            deps_met = all(
                data["tasks"].get(d) is not None and data["tasks"][d].get("status") == "done" for d in blocking_ids
            )
            results.append(
                TaskSummary(
                    id=tid,
                    title=info["title"],
                    status=info.get("status", "open"),
                    dependencies_met=deps_met,
                )
            )
        return results

    def list_ready(self) -> list[TaskSummary]:
        """Return all open tasks whose blocking dependencies are satisfied.

        Ranked by number of dependents (descending), then by task ID as a
        stable tiebreaker (approximates creation order).
        """
        data = self._manifest.load()
        all_tasks = data.get("tasks", {})

        # Build reverse-dependency map: task_id -> count of tasks that depend on it
        dependents_count: dict[str, int] = {}
        for info in all_tasks.values():
            raw_deps = info.get("dependencies", [])
            for dep_id in _extract_blocking_dep_ids(raw_deps):
                dependents_count[dep_id] = dependents_count.get(dep_id, 0) + 1

        results: list[TaskSummary] = []
        for tid, info in all_tasks.items():
            if info.get("status", "open") != "open":
                continue
            raw_deps = info.get("dependencies", [])
            blocking_ids = _extract_blocking_dep_ids(raw_deps)
            deps_met = all(all_tasks.get(d) is not None and all_tasks[d].get("status") == "done" for d in blocking_ids)
            if not deps_met:
                continue
            results.append(
                TaskSummary(
                    id=tid,
                    title=info["title"],
                    status="open",
                    dependencies_met=True,
                    dependents_count=dependents_count.get(tid, 0),
                )
            )

        # Sort: most dependents first, then by ID for stable ordering
        results.sort(key=lambda t: (-t.dependents_count, t.id))
        return results

    def update_status(self, task_id: str, status: str) -> None:
        """Update status in both the frontmatter file and the manifest."""
        update_file_status(
            self._tasks_dir / f"{task_id}.md",
            task_id,
            status,
            self._manifest,
            "tasks",
        )

    def add_comment(self, task_id: str, comment: str) -> None:
        """Append to Activity Log section with timestamp."""
        append_comment(self._tasks_dir / f"{task_id}.md", comment, timestamp_suffix=" (UTC)")

    def add_label(self, task_id: str, label: str) -> None:
        """Add a label to the task\'s frontmatter."""
        file_path = self._tasks_dir / f"{task_id}.md"
        content = file_path.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)
        labels: list[str] = fm.get("labels", [])
        if label not in labels:
            labels.append(label)
            fm["labels"] = labels
            fm["updated"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            file_path.write_text(render_frontmatter(fm, body), encoding="utf-8")

    def remove_label(self, task_id: str, label: str) -> None:
        """Remove a label from the task\'s frontmatter."""
        file_path = self._tasks_dir / f"{task_id}.md"
        content = file_path.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)
        labels: list[str] = fm.get("labels", [])
        if label in labels:
            labels.remove(label)
            fm["labels"] = labels
            fm["updated"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            file_path.write_text(render_frontmatter(fm, body), encoding="utf-8")

    def assign(self, task_id: str, assignee: str) -> None:
        """Update frontmatter assignee."""
        file_path = self._tasks_dir / f"{task_id}.md"
        content = file_path.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)
        fm["assignee"] = assignee
        fm["updated"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        file_path.write_text(render_frontmatter(fm, body), encoding="utf-8")

    def update_gates(self, task_id: str, gates: list[Gate]) -> None:
        """Persist updated gates for *task_id* in file and manifest."""
        file_path = self._tasks_dir / f"{task_id}.md"
        content = file_path.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)
        fm["gates"] = _serialize_gates(gates)
        file_path.write_text(render_frontmatter(fm, body), encoding="utf-8")

        data = self._manifest.load()
        if task_id in data.get("tasks", {}):
            data["tasks"][task_id]["gates"] = _serialize_gates(gates)
            self._manifest.save(data)

    def update_frontmatter(self, task_id: str, fields: dict[str, object]) -> None:
        """Merge *fields* into the task's YAML frontmatter and persist."""
        file_path = self._tasks_dir / f"{task_id}.md"
        content = file_path.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)
        fm.update(fields)
        fm["updated"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        file_path.write_text(render_frontmatter(fm, body), encoding="utf-8")

    # ------------------------------------------------------------------
    # Compaction
    # ------------------------------------------------------------------

    def compact_task(self, task_id: str) -> CompactedTask:
        """Compact a completed task -- replace file with compacted version."""
        task = self.get_task(task_id)
        compactor = TaskCompactor()
        compacted = compactor.compact_task(task)
        self._write_compacted(task_id, compacted)
        return compacted

    def compact_all_done(self, *, dry_run: bool = False) -> list[str]:
        """Compact all done/closed tasks. Returns list of compacted IDs."""
        data = self._manifest.load()
        compactor = TaskCompactor()
        compacted_ids: list[str] = []
        for tid, info in data.get("tasks", {}).items():
            status = info.get("status", "open")
            if status not in {"done", "closed"}:
                continue
            if info.get("compacted"):
                continue
            if dry_run:
                compacted_ids.append(tid)
                continue
            task = self.get_task(tid)
            compacted = compactor.compact_task(task)
            self._write_compacted(tid, compacted)
            compacted_ids.append(tid)
        return compacted_ids

    def _write_compacted(
        self,
        task_id: str,
        compacted: CompactedTask,
    ) -> None:
        """Write a compacted task to disk and update the manifest."""
        file_path = self._tasks_dir / f"{task_id}.md"
        file_content = file_path.read_text(encoding="utf-8")
        fm, _body = parse_frontmatter(file_content)
        fm["compacted"] = True
        fm["compacted_at"] = compacted.compacted_at
        fm["updated"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        body_parts: list[str] = []
        body_parts.append("## Summary")
        body_parts.append("")
        body_parts.append(compacted.summary)
        body_parts.append("")
        if compacted.key_decisions:
            body_parts.append("## Key Decisions")
            body_parts.append("")
            body_parts.extend(f"- {d}" for d in compacted.key_decisions)
            body_parts.append("")
        if compacted.files_modified:
            body_parts.append("## Files Modified")
            body_parts.append("")
            body_parts.extend(f"- {fp}" for fp in compacted.files_modified)
            body_parts.append("")
        if compacted.original_description:
            body_parts.append("## Original Description")
            body_parts.append("")
            body_parts.append(compacted.original_description)
            body_parts.append("")
        body = chr(10).join(body_parts)
        file_path.write_text(render_frontmatter(fm, body), encoding="utf-8")
        data = self._manifest.load()
        if task_id in data.get("tasks", {}):
            data["tasks"][task_id]["compacted"] = True
            self._manifest.save(data)

    def check_dependencies(self, task_id: str) -> list[DependencyStatus]:
        """Read manifest, check each blocking dependency\'s status."""
        data = self._manifest.load()
        task_info = data.get("tasks", {}).get(task_id, {})
        raw_deps = task_info.get("dependencies", [])
        blocking_ids = _extract_blocking_dep_ids(raw_deps)
        result: list[DependencyStatus] = []
        for dep_id in blocking_ids:
            dep_info = data.get("tasks", {}).get(dep_id, {})
            result.append(
                DependencyStatus(
                    task_id=dep_id,
                    title=dep_info.get("title", "Unknown"),
                    resolved=dep_info.get("status") == "done",
                )
            )
        return result


def _serialize_deps(deps: list[str | Dependency]) -> list[str | dict[str, str]]:
    """Serialize dependencies for YAML frontmatter.

    Bare strings stay as strings. Dependency objects become dicts.
    """
    result: list[str | dict[str, str]] = []
    for dep in deps:
        if isinstance(dep, Dependency):
            result.append({"task_id": dep.task_id, "type": dep.type.value})
        else:
            result.append(dep)
    return result


def _deserialize_deps(raw: list[str | dict[str, str]]) -> list[str | Dependency]:
    """Deserialize dependencies from YAML frontmatter.

    Plain strings stay as strings. Dicts with task_id/type become Dependency objects.
    """
    result: list[str | Dependency] = []
    for item in raw:
        if isinstance(item, dict):
            result.append(
                Dependency(
                    task_id=item.get("task_id", ""),
                    type=DependencyType(item.get("type", "blocks")),
                )
            )
        else:
            result.append(str(item))
    return result


def _serialize_gates(gates: list[Gate]) -> list[dict[str, object]]:
    """Serialize Gate objects into dicts for YAML frontmatter."""
    result: list[dict[str, object]] = []
    for gate in gates:
        entry: dict[str, object] = {
            "id": gate.id,
            "type": gate.type.value,
            "description": gate.description,
            "status": gate.status.value,
        }
        if gate.config:
            entry["config"] = dict(gate.config)
        if gate.resolved_at:
            entry["resolved_at"] = gate.resolved_at
        result.append(entry)
    return result


def _deserialize_gates(raw: list[dict[str, object]]) -> list[Gate]:
    """Deserialize gate dicts from YAML frontmatter into Gate objects."""
    result: list[Gate] = []
    for item in raw:
        if isinstance(item, dict):
            config_raw = item.get("config", {})
            config = {str(k): str(v) for k, v in config_raw.items()} if isinstance(config_raw, dict) else {}
            result.append(
                Gate(
                    id=str(item.get("id", "")),
                    type=GateType(str(item.get("type", "custom"))),
                    description=str(item.get("description", "")),
                    status=GateStatus(str(item.get("status", "pending"))),
                    config=config,
                    resolved_at=str(item["resolved_at"]) if item.get("resolved_at") else None,
                )
            )
    return result


def _extract_blocking_dep_ids(raw_deps: list[str | dict[str, str]]) -> list[str]:
    """Extract task IDs of blocking dependencies from raw manifest/frontmatter data.

    Bare strings are treated as blocking. Dict entries are only blocking
    if their type is in BLOCKING_DEPENDENCY_TYPES.
    """
    result: list[str] = []
    for dep in raw_deps:
        if isinstance(dep, dict):
            dep_type = DependencyType(dep.get("type", "blocks"))
            if dep_type in BLOCKING_DEPENDENCY_TYPES:
                result.append(dep.get("task_id", ""))
        else:
            # Bare string = blocking (backward compat)
            result.append(str(dep))
    return result


def _extract_section(body: str, heading: str) -> str:
    """Extract text under a ## heading, stopping at the next ## heading."""
    in_section = False
    lines: list[str] = []
    for line in body.splitlines():
        if line.strip() == f"## {heading}":
            in_section = True
            continue
        if in_section and line.strip().startswith("## "):
            break
        if in_section:
            lines.append(line)
    return "\n".join(lines).strip()

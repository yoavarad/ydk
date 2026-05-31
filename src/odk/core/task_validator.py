"""DAG validation and coverage checking — Stage 02 business logic."""

from __future__ import annotations

import os.path
from collections import defaultdict, deque
from typing import TYPE_CHECKING, cast

import yaml

from odk.models.task import DagValidationResult, Task

if TYPE_CHECKING:
    from pathlib import Path

    from odk.models.pm import EpicSummary, StorySummary, TaskSummary


def validate_dag(tasks: list[Task]) -> DagValidationResult:
    """Validate task dependency graph using Kahn's algorithm.

    Only *blocking* dependency types (blocks, conditional-blocks, waits-for)
    create execution edges.  Non-blocking types (validates, caused-by,
    discovered-from, supersedes, related) are metadata and do not affect
    execution order or cycle detection.

    Returns parallel sets, critical path, fan-out, and cycle detection.
    """
    if not tasks:
        return DagValidationResult(
            valid=True,
            cycles=None,
            parallel_sets=[],
            critical_path=[],
            critical_path_length=0,
            fan_out={},
        )

    task_ids = {t.id for t in tasks}

    # Check for self-dependencies (self-loops).
    self_loops: list[str] = [t.id for t in tasks for dep_id in t.blocking_dep_ids() if dep_id == t.id]

    if self_loops:
        descriptions = [f"{tid} depends on itself" for tid in sorted(set(self_loops))]
        return DagValidationResult(
            valid=False,
            cycles=[f"Self-dependency detected: {'; '.join(descriptions)}"],
            parallel_sets=[],
            critical_path=[],
            critical_path_length=0,
            fan_out={},
        )

    # Validate that all dependency targets exist in the task set.
    unresolved: dict[str, list[str]] = defaultdict(list)
    for t in tasks:
        for dep_id in t.blocking_dep_ids():
            if dep_id not in task_ids:
                unresolved[t.id].append(dep_id)

    if unresolved:
        descriptions: list[str] = []
        for tid, missing in sorted(unresolved.items()):
            descriptions.append(f"{tid} -> {', '.join(missing)}")
        return DagValidationResult(
            valid=False,
            error=f"Unresolved dependency references: {'; '.join(descriptions)}",
            cycles=None,
            parallel_sets=[],
            critical_path=[],
            critical_path_length=0,
            fan_out={},
        )

    # Build adjacency list (dependency -> dependent) and in-degree map.
    # Only blocking dependency types create execution edges.
    adj: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {t.id: 0 for t in tasks}
    for t in tasks:
        for dep_id in t.blocking_dep_ids():
            if dep_id in task_ids:
                adj[dep_id].append(t.id)
                in_degree[t.id] += 1

    # Kahn's algorithm: BFS with zero in-degree queue
    queue: deque[str] = deque()
    for tid in sorted(in_degree):  # sorted for deterministic output
        if in_degree[tid] == 0:
            queue.append(tid)

    parallel_sets: list[list[str]] = []
    topo_order: list[str] = []

    while queue:
        # All items currently in the queue form a parallel wave
        wave = sorted(queue)  # sorted for determinism
        parallel_sets.append(wave)
        next_queue: deque[str] = deque()
        for _ in range(len(queue)):
            node = queue.popleft()
            topo_order.append(node)
            for neighbor in sorted(adj[node]):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    next_queue.append(neighbor)
        queue = next_queue

    # Cycle detection: if not all tasks were visited, there's a cycle
    if len(topo_order) < len(tasks):
        cycle_nodes = sorted(tid for tid in task_ids if tid not in set(topo_order))
        if cycle_nodes:
            cycle_description = " -> ".join(cycle_nodes) + " -> " + cycle_nodes[0]
        else:
            cycle_description = "Cycle detected but participants could not be identified"
        return DagValidationResult(
            valid=False,
            cycles=[cycle_description],
            parallel_sets=[],
            critical_path=[],
            critical_path_length=0,
            fan_out={},
        )

    # Compute critical path via longest-path DFS (using dynamic programming)
    dist: dict[str, int] = {tid: 1 for tid in task_ids}
    predecessor: dict[str, str | None] = {tid: None for tid in task_ids}

    for node in topo_order:
        for neighbor in adj[node]:
            if dist[node] + 1 > dist[neighbor]:
                dist[neighbor] = dist[node] + 1
                predecessor[neighbor] = node

    # Find the endpoint of the longest path
    end_node = max(sorted(dist), key=lambda n: dist[n])
    critical_path: list[str] = []
    current: str | None = end_node
    while current is not None:
        critical_path.append(current)
        current = predecessor[current]
    critical_path.reverse()

    # Fan-out: number of direct dependents per task
    fan_out: dict[str, int] = {tid: len(adj[tid]) for tid in task_ids if adj[tid]}

    return DagValidationResult(
        valid=True,
        cycles=None,
        parallel_sets=parallel_sets,
        critical_path=critical_path,
        critical_path_length=len(critical_path),
        fan_out=fan_out,
    )


def check_coverage(
    spec_sections: dict[str, list[str]],
    story_refs: dict[str, set[str]],
    exclude_patterns: list[str] | None = None,
) -> list[str]:
    """Check that every spec section has a story. Returns uncovered sections.

    Matching logic: a spec section is considered covered if any story ref
    matches either exactly or by filename (basename). This handles cases
    where story ``spec_refs`` use full paths like ``docs/specs/01-core-domain.md``
    while spec_sections keys also use full paths.

    ``exclude_patterns`` is a list of filename patterns (e.g. ``"08-glossary.md"``)
    that should be excluded from coverage checking entirely.
    """
    excludes = set(exclude_patterns or [])

    # Build a lookup from basename -> set of full-path keys in story_refs
    basename_to_refs: dict[str, set[str]] = {}
    for ref_key in story_refs:
        base = os.path.basename(ref_key)
        basename_to_refs.setdefault(base, set()).update(story_refs[ref_key])
        # Also keep full key mapping
        basename_to_refs.setdefault(ref_key, set()).update(story_refs[ref_key])

    uncovered: list[str] = []
    for section in sorted(spec_sections):
        section_basename = os.path.basename(section)

        # Skip excluded files
        if section_basename in excludes or section in excludes:
            continue

        # Check direct match
        if story_refs.get(section):
            continue

        # Check basename match (story ref "01-core-domain.md" matches
        # spec section "docs/specs/01-core-domain.md")
        if basename_to_refs.get(section_basename):
            continue

        uncovered.append(section)

    return uncovered


# ---------------------------------------------------------------------------
# Component coverage
# ---------------------------------------------------------------------------


def check_component_coverage(
    components_dir: Path,
    task_component_refs: dict[str, list[str]],
) -> list[str]:
    """Check that every component in components_dir is referenced by at least one task.

    Returns list of uncovered component IDs.
    """
    if not components_dir.is_dir():
        return []

    # Collect all component IDs from YAML files
    all_ids: set[str] = set()
    for yaml_file in components_dir.rglob("*.yaml"):
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and "id" in data:
            all_ids.add(str(data["id"]))

    if not all_ids:
        return []

    # Collect all referenced IDs across tasks
    referenced: set[str] = set()
    for refs in task_component_refs.values():
        referenced.update(refs)

    uncovered = sorted(cid for cid in all_ids if cid not in referenced)
    return uncovered


# ---------------------------------------------------------------------------
# Hierarchy validation
# ---------------------------------------------------------------------------


def check_hierarchy(
    tasks: list[TaskSummary],
    stories: list[StorySummary],
    epics: list[EpicSummary],
) -> list[str]:
    """Check that every task belongs to a story and every story to an epic.

    Also checks for epics with no stories.
    Returns list of warning strings.
    """
    warnings: list[str] = []

    # Tasks without a story
    warnings.extend(
        f"Task {t.id} has no story_id (orphaned task)" for t in tasks if not (getattr(t, "story_id", None) or "")
    )

    # Stories without an epic
    warnings.extend(
        f"Story {s.id} has no epic_id (orphaned story)" for s in stories if not (getattr(s, "epic_id", None) or "")
    )

    # Epics with no stories
    story_epic_ids = {s.epic_id for s in stories if getattr(s, "epic_id", None)}
    warnings.extend(f"Epic {e.id} has no stories" for e in epics if e.id not in story_epic_ids)

    return sorted(warnings)


def check_story_completeness(
    stories: list[StorySummary],
    story_details: dict[str, object] | None = None,
) -> list[str]:
    """Check stories for missing spec_refs and acceptance criteria.

    ``story_details`` maps story ID to an object with ``spec_refs`` and
    ``acceptance_criteria`` attributes (e.g. StoryDetail or a dict).
    """
    warnings: list[str] = []
    if not story_details:
        return warnings

    for s in stories:
        detail = story_details.get(s.id)
        if detail is None:
            continue

        spec_refs = getattr(detail, "spec_refs", None) or []
        if not spec_refs:
            warnings.append(f"Story {s.id} has no spec_refs")

        acceptance = getattr(detail, "acceptance_criteria", None) or []
        if not acceptance:
            warnings.append(f"Story {s.id} has no acceptance criteria")

    return sorted(warnings)


# ---------------------------------------------------------------------------
# Ref validation helpers
# ---------------------------------------------------------------------------


def validate_component_ref(ref: str, components_dir: Path) -> str | None:
    """Return an error message if *ref* does not resolve to an existing component file.

    Returns ``None`` when valid.
    """
    if not ref.startswith("odk:"):
        return f"Component ref '{ref}' does not start with 'odk:'"

    parts = ref.split(":", 2)
    if len(parts) != 3 or not parts[1] or not parts[2]:
        return f"Invalid component ref format: {ref}"

    type_name = parts[1]
    namespace_name = parts[2]
    if "/" in namespace_name:
        last_slash = namespace_name.rfind("/")
        namespace = namespace_name[:last_slash]
        name = namespace_name[last_slash + 1 :]
        path = components_dir / type_name / namespace / f"{name}.yaml"
    else:
        path = components_dir / type_name / f"{namespace_name}.yaml"

    if not path.is_file():
        return f"Component {ref} not found at {path}"
    return None


def validate_spec_ref(ref: str, project_root: Path) -> str | None:
    """Return an error message if *ref* does not exist relative to *project_root*.

    Returns ``None`` when valid.
    """
    path = project_root / ref
    if not path.is_file():
        return f"Spec file {ref} not found"
    return None


# ---------------------------------------------------------------------------
# Batch YAML validation
# ---------------------------------------------------------------------------

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


def validate_batch_yaml(
    data: dict[str, object],
    components_dir: Path | None = None,
    specs_dir: Path | None = None,
) -> list[str]:
    """Pre-flight validation for batch YAML before any API calls.

    Returns list of errors. Empty list means valid.
    """
    errors: list[str] = []

    # -- Epics ---------------------------------------------------------------
    epics_raw = data.get("epics") or []
    epic_ids: set[str] = set()
    if isinstance(epics_raw, list):
        for idx, item in enumerate(epics_raw):
            if not isinstance(item, dict):
                errors.append(f"epics[{idx}]: not a mapping")
                continue
            item_map = cast("dict[str, object]", item)
            if not item_map.get("title"):
                errors.append(f"epics[{idx}]: missing required field 'title'")
            eid = item_map.get("id")
            if eid:
                epic_ids.add(str(eid))

    # -- Stories -------------------------------------------------------------
    stories_raw = data.get("stories") or []
    story_ids: set[str] = set()
    if isinstance(stories_raw, list):
        for idx, item in enumerate(stories_raw):
            if not isinstance(item, dict):
                errors.append(f"stories[{idx}]: not a mapping")
                continue
            item_map = cast("dict[str, object]", item)
            if not item_map.get("title"):
                errors.append(f"stories[{idx}]: missing required field 'title'")
            sid = item_map.get("id")
            if sid:
                story_ids.add(str(sid))
            # Epic reference check
            epic_ref = item_map.get("epic_id") or item_map.get("epic")
            if epic_ref and str(epic_ref) not in epic_ids:
                errors.append(f"stories[{idx}]: epic_id '{epic_ref}' not found in YAML")

    # -- Tasks ---------------------------------------------------------------
    tasks_raw = data.get("tasks") or []
    task_ids: set[str] = set()
    if isinstance(tasks_raw, list):
        for idx, item in enumerate(tasks_raw):
            if not isinstance(item, dict):
                errors.append(f"tasks[{idx}]: not a mapping")
                continue
            item_map = cast("dict[str, object]", item)
            if not item_map.get("title"):
                errors.append(f"tasks[{idx}]: missing required field 'title'")

            tid = item_map.get("id")
            if tid:
                task_ids.add(str(tid))

    # Second pass for tasks: check deps, refs, story refs
    if isinstance(tasks_raw, list):
        for idx, item in enumerate(tasks_raw):
            if not isinstance(item, dict):
                continue
            item_map = cast("dict[str, object]", item)
            tid = str(item_map.get("id", f"tasks[{idx}]"))

            # Story reference
            story_ref = item_map.get("story_id") or item_map.get("story")
            if story_ref and str(story_ref) not in story_ids:
                errors.append(f"tasks[{idx}]: story '{story_ref}' not found in YAML")

            # Dependencies
            deps = item_map.get("depends_on") or []
            if isinstance(deps, list):
                for dep in deps:
                    dep_str = str(dep)
                    dep_id = dep_str.split(":")[0] if ":" in dep_str else dep_str
                    dep_type = dep_str.split(":", 1)[1] if ":" in dep_str else "blocks"

                    # Self-dependency check
                    if dep_id == tid:
                        errors.append(f"tasks[{idx}]: self-dependency on '{tid}'")

                    # Dep exists in YAML
                    if dep_id not in task_ids:
                        errors.append(f"tasks[{idx}]: depends_on '{dep_id}' not found in YAML")

                    # Valid type
                    if dep_type not in _VALID_DEP_TYPES:
                        errors.append(f"tasks[{idx}]: invalid dependency type '{dep_type}'")

            # Component refs
            crefs = item_map.get("component_refs") or []
            if isinstance(crefs, list) and components_dir is not None:
                for ref in crefs:
                    err = validate_component_ref(str(ref), components_dir)
                    if err:
                        errors.append(f"tasks[{idx}]: {err}")

            # Spec refs
            srefs = item_map.get("spec_refs") or []
            if isinstance(srefs, list) and specs_dir is not None:
                for ref in srefs:
                    err = validate_spec_ref(str(ref), specs_dir)
                    if err:
                        errors.append(f"tasks[{idx}]: {err}")

    return errors

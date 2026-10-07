"""GitHub-backed TaskRepository — uses the gh CLI via subprocess."""

from __future__ import annotations

import builtins
import logging
import re
from typing import TYPE_CHECKING

from ydk.models.pm import Dependency, DependencyStatus, TaskCreate, TaskDetail, TaskStatus, TaskSummary
from ydk.models.task import is_blocking_dependency
from ydk.repositories.github._helpers import (
    GH_JSON_FIELDS,
    GH_LIST_LIMIT,
    check_result,
    label_names,
    load_json_stdout,
    run_gh,
)
from ydk.repositories.github.parser import (
    parse_task_detail,
    render_dependency,
    render_gate_line,
    render_task_body,
    set_body_field,
)

if TYPE_CHECKING:
    from ydk.models.compaction import CompactedTask
    from ydk.models.gate import Gate

_list = builtins.list

logger = logging.getLogger(__name__)

# update_frontmatter key -> ``**Label**:`` body field that parse_task_detail reads back.
_BODY_FIELD_LABELS: dict[str, str] = {
    "dependencies": "Dependencies",
    "tdd_stage": "TDD stage",
    "session_id": "Session",
}


def _dep_to_str(dep: object) -> str:
    """Render a Dependency, ``{"task_id", "type"}`` dict, or plain value as ``ID`` / ``ID (type)``."""
    if isinstance(dep, dict):
        dep = Dependency.model_validate(dep)
    if isinstance(dep, Dependency):
        return render_dependency(dep.task_id, dep.type)
    return str(dep)


def _blocking_dep_numbers(task: TaskDetail) -> tuple[_list[int], bool]:
    """Return issue numbers of *task*'s blocking deps and whether any was unresolvable.

    Non-blocking types (``related``, ``validates``, ...) are ignored. Unresolvable
    IDs are logged as a warning naming the task and dependency.
    """
    numbers: _list[int] = []
    unresolved = False
    for dep in task.dependencies:
        if not is_blocking_dependency(dep):
            continue
        dep_id = dep.task_id if isinstance(dep, Dependency) else str(dep)
        try:
            numbers.append(_extract_issue_number(dep_id))
        except ValueError:
            logger.warning("Task #%s has unresolvable dependency %r; treating it as unmet", task.number, dep_id)
            unresolved = True
    return numbers, unresolved


class GitHubTaskRepository:
    """TaskRepository implementation backed by GitHub Issues via gh CLI."""

    def __init__(self, task_label: str = "task") -> None:
        self._task_label = task_label

    # -- create ---------------------------------------------------------------

    def create(self, task: TaskCreate) -> TaskDetail:
        """Create a GitHub Issue from a TaskCreate and return the parsed TaskDetail."""
        body = render_task_body(task)
        cmd: list[str] = [
            "gh",
            "issue",
            "create",
            "--title",
            task.title,
            "--body",
            body,
            "--label",
            self._task_label,
        ]
        for label in task.labels:
            cmd.extend(["--label", label])
        if task.milestone:
            cmd.extend(["--milestone", task.milestone])

        result = run_gh(cmd)
        check_result(result, "issue create")

        # gh issue create prints the URL; extract number from it
        url = result.stdout.strip()
        issue_number = int(url.rstrip("/").split("/")[-1])

        return parse_task_detail(
            number=issue_number,
            title=task.title,
            body=body,
            state="OPEN",
            labels=[self._task_label, *task.labels],
            url=url,
        )

    # -- get ------------------------------------------------------------------

    def get(self, issue_number: int) -> TaskDetail:
        """Fetch a single issue by number and parse it."""
        cmd = [
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--json",
            GH_JSON_FIELDS,
        ]
        result = run_gh(cmd)
        check_result(result, "issue view")
        data = load_json_stdout(result, "issue view")
        return parse_task_detail(
            number=data["number"],
            title=data["title"],
            body=data.get("body", ""),
            state=data["state"],
            labels=label_names(data.get("labels", [])),
            url=data.get("url", ""),
        )

    # -- list -----------------------------------------------------------------

    def list(
        self,
        milestone: str | None = None,
        labels: _list[str] | None = None,
        status: str = "open",
    ) -> _list[TaskDetail]:
        """List task issues with optional filters.

        ``status`` accepts gh's native states (``open``/``closed``/``all``) as
        well as the higher-level lifecycle statuses used across YDK
        (``done``/``in-progress``/``in-review``/``blocked``), which gh does
        not understand directly:

        - ``done`` -> ``--state closed``
        - ``in-progress`` / ``in-review`` -> ``--state open`` + a label filter
        - ``blocked`` -> ``--state open``, then filtered post-fetch by the
          parsed ``TaskStatus`` (labels vary: ``blocked-by-code``,
          ``blocked-by-decision``, etc.)
        """
        extra_label: str | None = None
        if status == "done":
            gh_state = "closed"
        elif status in ("in-progress", "in-review"):
            gh_state = "open"
            extra_label = status
        elif status == "blocked":
            gh_state = "open"
        else:
            gh_state = status

        cmd: list[str] = [
            "gh",
            "issue",
            "list",
            "--json",
            GH_JSON_FIELDS,
            "--state",
            gh_state,
            "--limit",
            str(GH_LIST_LIMIT),
            "--label",
            self._task_label,
        ]
        if milestone:
            cmd.extend(["--milestone", milestone])
        for lbl in labels or []:
            cmd.extend(["--label", lbl])
        if extra_label:
            cmd.extend(["--label", extra_label])

        result = run_gh(cmd)
        check_result(result, "issue list")

        items: list[dict] = load_json_stdout(result, "issue list")
        details = [
            parse_task_detail(
                number=item["number"],
                title=item["title"],
                body=item.get("body", ""),
                state=item["state"],
                labels=label_names(item.get("labels", [])),
                url=item.get("url", ""),
            )
            for item in items
        ]

        if status == "blocked":
            details = [d for d in details if d.status in (TaskStatus.BLOCKED_BY_CODE, TaskStatus.BLOCKED_BY_DECISION)]
        return details

    # -- update_status --------------------------------------------------------

    def update_status(self, issue_number: int | str, status: str) -> None:
        """Update an issue's status by toggling open/closed or adding labels."""
        num = str(issue_number)
        if status in ("closed", "done"):
            cmd = ["gh", "issue", "close", num]
        elif status == "open":
            cmd = ["gh", "issue", "reopen", num]
        else:
            # For in-progress / blocked, we add a label
            run_gh(["gh", "label", "create", status, "--force"])
            cmd = ["gh", "issue", "edit", num, "--add-label", status]
        result = run_gh(cmd)
        check_result(result, "update_status")

    # -- add_comment ----------------------------------------------------------

    def add_comment(self, issue_number: int | str, comment: str) -> None:
        """Add a comment to the issue."""
        cmd = ["gh", "issue", "comment", str(issue_number), "--body", comment]
        result = run_gh(cmd)
        check_result(result, "add_comment")

    # -- lifecycle-compatible aliases ----------------------------------------
    # These methods allow GitHubTaskRepository to satisfy the
    # LifecycleTaskRepository protocol used by TaskLifecycle and CLI commands.

    def create_task(self, task: TaskCreate) -> TaskDetail:
        """Alias for create() — lifecycle-compatible."""
        return self.create(task)

    def get_task(self, task_id: str) -> TaskDetail:
        """Get task by ID string (e.g. 'T-001' or '42'). Extracts issue number."""
        issue_number = _extract_issue_number(task_id)
        return self.get(issue_number)

    def list_tasks(self, state: str = "open") -> _list[TaskSummary]:
        """List tasks — lifecycle-compatible. Returns TaskSummary list."""
        details = self.list(status=state)
        # Closed = done for dependency resolution. state="all" already includes closed tasks.
        if state == "all":
            closed_details = [d for d in details if d.status == TaskStatus.DONE]
        else:
            closed_details = self.list(status="closed")
        done_ids = {d.number for d in closed_details}

        summaries: _list[TaskSummary] = []
        for d in details:
            dep_nums, unresolved = _blocking_dep_numbers(d)
            deps_met = not unresolved and all(n in done_ids for n in dep_nums)
            summaries.append(
                TaskSummary(
                    id=str(d.number),
                    title=d.title,
                    status=d.status,
                    dependencies_met=deps_met,
                )
            )
        return summaries

    def assign(self, task_id: str, assignee: str) -> None:
        """Assign a user to the issue. Silently ignores invalid assignees."""
        issue_number = _extract_issue_number(task_id)
        cmd = ["gh", "issue", "edit", str(issue_number), "--add-assignee", assignee]
        run_gh(cmd)  # Best-effort — ignore failures (e.g. "agent" not a real user)

    def add_label(self, task_id: str, label: str) -> None:
        """Add a label to the issue."""
        issue_number = _extract_issue_number(task_id)
        # Ensure label exists, then add it
        run_gh(["gh", "label", "create", label, "--force"])
        cmd = ["gh", "issue", "edit", str(issue_number), "--add-label", label]
        result = run_gh(cmd)
        check_result(result, "add_label")

    def remove_label(self, task_id: str, label: str) -> None:
        """Remove a label from the issue."""
        issue_number = _extract_issue_number(task_id)
        cmd = ["gh", "issue", "edit", str(issue_number), "--remove-label", label]
        run_gh(cmd)  # ignore errors if label doesn't exist

    def update_frontmatter(self, task_id: str, fields: dict[str, object]) -> None:
        """Update ``**Field**:`` lines in a GitHub issue body (add if missing, replace if present).

        Raises ValueError for keys this backend cannot persist, rather than
        silently dropping them.
        """
        unknown = sorted(set(fields) - set(_BODY_FIELD_LABELS))
        if unknown:
            supported = ", ".join(sorted(_BODY_FIELD_LABELS))
            raise ValueError(f"Unsupported frontmatter key(s) for GitHub backend: {unknown} (supported: {supported})")

        issue_number = _extract_issue_number(task_id)

        # Reconstruct the body with updated fields
        cmd = ["gh", "issue", "view", str(issue_number), "--json", "body", "-q", ".body"]
        result = run_gh(cmd)
        check_result(result, "issue view body")
        body = result.stdout.strip()

        for key, value in fields.items():
            if key == "dependencies":
                dep_list = value if isinstance(value, list) else [value]
                text = ", ".join(_dep_to_str(d) for d in dep_list)
            else:
                text = "" if value is None else str(value)
            body = set_body_field(body, _BODY_FIELD_LABELS[key], text)

        # Update the issue
        update_cmd = ["gh", "issue", "edit", str(issue_number), "--body", body]
        update_result = run_gh(update_cmd)
        check_result(update_result, "issue edit body")

    def task_exists(self, task_id: str) -> bool:
        """Check if a task (issue) exists in the GitHub repository."""
        try:
            issue_number = _extract_issue_number(task_id)
            self.get(issue_number)
            return True
        except (RuntimeError, ValueError):
            return False

    def check_dependencies(self, task_id: str) -> _list[DependencyStatus]:
        """Check dependency status by reading the issue body for Dependencies field."""

        issue_number = _extract_issue_number(task_id)
        task = self.get(issue_number)
        deps = task.dependencies or []
        results: _list[DependencyStatus] = []
        for dep in deps:
            dep_id = dep.task_id if isinstance(dep, Dependency) else dep
            try:
                dep_number = _extract_issue_number(dep_id)
                dep_task = self.get(dep_number)
                resolved = dep_task.status in ("done", "closed")
            except (RuntimeError, ValueError):
                resolved = False
            results.append(DependencyStatus(task_id=dep_id, title="", resolved=resolved))
        return results

    # -- list_ready -----------------------------------------------------------

    def list_ready(self) -> _list[TaskSummary]:
        """Return open tasks whose blocking dependencies are all satisfied.

        Tasks already claimed (in-progress, in-review) or blocked are excluded.

        Ranked by number of dependents (descending), then by issue number.
        """
        open_tasks = self.list(status="open")
        closed_tasks = self.list(status="closed")
        closed_numbers = {d.number for d in closed_tasks}

        blocking = {d.number: _blocking_dep_numbers(d) for d in open_tasks}

        # Build reverse-dependency map: issue_number -> count of blocking dependents
        dependents_count: dict[int, int] = {}
        for dep_nums, _unresolved in blocking.values():
            for dep_num in dep_nums:
                dependents_count[dep_num] = dependents_count.get(dep_num, 0) + 1

        results: _list[TaskSummary] = []
        for d in open_tasks:
            if d.status != TaskStatus.OPEN:
                continue
            dep_nums, unresolved = blocking[d.number]
            if unresolved or any(n not in closed_numbers for n in dep_nums):
                continue
            results.append(
                TaskSummary(
                    id=str(d.number),
                    title=d.title,
                    status=d.status,
                    dependencies_met=True,
                    dependents_count=dependents_count.get(d.number, 0),
                )
            )

        results.sort(key=lambda t: (-t.dependents_count, t.id))
        return results

    # -- update_gates ---------------------------------------------------------

    def update_gates(self, task_id: str, gates: _list[Gate]) -> None:
        """Persist updated gates by editing the issue body's **Gates** section."""
        issue_number = _extract_issue_number(task_id)

        # Read current body
        cmd = ["gh", "issue", "view", str(issue_number), "--json", "body", "-q", ".body"]
        result = run_gh(cmd)
        check_result(result, "issue view body")
        body = result.stdout.strip()

        # Render gates block
        gate_lines = [render_gate_line(g) for g in gates]
        gates_block = "\n".join(gate_lines) if gate_lines else "_No gates_"
        new_section = f"### Gates\n{gates_block}"

        # Replace or append
        if "### Gates" in body:
            body = re.sub(
                r"### Gates\n.*?(?=\n###|\Z)",
                new_section,
                body,
                flags=re.DOTALL,
            )
        else:
            body = body.rstrip() + "\n\n" + new_section

        update_cmd = ["gh", "issue", "edit", str(issue_number), "--body", body]
        update_result = run_gh(update_cmd)
        check_result(update_result, "issue edit body (gates)")

    # -- compaction -----------------------------------------------------------

    def compact_task(self, task_id: str) -> CompactedTask:
        """Compact a completed task by posting a summary comment and archiving it.

        Uses the same ``TaskCompactor`` logic as the local backend. The
        original issue body is never modified -- the compacted summary is
        posted as a comment and the issue is tagged with an "archived"
        label instead, so the source-of-truth body is preserved.
        """
        from ydk.core.compaction import TaskCompactor

        issue_number = _extract_issue_number(task_id)
        task = self.get(issue_number)
        compactor = TaskCompactor()
        compacted = compactor.compact_task(task)

        lines: _list[str] = [
            "### Summary",
            compacted.summary,
            "",
        ]
        if compacted.key_decisions:
            lines.append("### Key Decisions")
            lines.extend(f"- {d}" for d in compacted.key_decisions)
            lines.append("")
        if compacted.files_modified:
            lines.append("### Files Modified")
            lines.extend(f"- `{fp}`" for fp in compacted.files_modified)
            lines.append("")

        comment_body = "\n".join(lines)
        self.add_comment(issue_number, comment_body)
        self.add_label(task_id, "archived")

        return compacted

    def compact_all_done(self, *, dry_run: bool = False) -> _list[str]:
        """Compact all closed tasks. Returns list of compacted issue numbers."""
        closed = self.list(status="closed")
        compacted_ids: _list[str] = []
        for task in closed:
            tid = str(task.number)
            if dry_run:
                compacted_ids.append(tid)
                continue
            try:
                self.compact_task(tid)
                compacted_ids.append(tid)
            except (RuntimeError, ValueError):
                pass  # skip tasks that fail to compact
        return compacted_ids


_ISSUE_REF = re.compile(r"#?([0-9]+)")


def _extract_issue_number(task_id: str) -> int:
    """Extract the GitHub issue number from ``N`` or ``#N``.

    Raises:
        ValueError: If ``task_id`` is not ``N`` or ``#N`` (e.g. ``T-001``,
            ``T-5e9dbd18``, ``QD-abc123``). Batch placeholders must be resolved
            via ``ydk.core.task_ref.resolve_task_ref`` before calling this.
    """
    match = _ISSUE_REF.fullmatch(str(task_id).strip())
    if match is None:
        msg = f"{task_id!r} is not a GitHub issue number; remote=github expects N or #N"
        raise ValueError(msg)
    return int(match.group(1))

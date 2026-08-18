"""GitHub-backed TaskRepository — uses the gh CLI via subprocess."""

from __future__ import annotations

import builtins
import json
import re
from typing import TYPE_CHECKING

from ydk.models.pm import Dependency, DependencyStatus, TaskCreate, TaskDetail, TaskSummary
from ydk.repositories.github._helpers import GH_JSON_FIELDS, check_result, label_names, run_gh
from ydk.repositories.github.parser import parse_task_detail, render_task_body

if TYPE_CHECKING:
    from ydk.models.compaction import CompactedTask
    from ydk.models.gate import Gate

_list = builtins.list


def _dep_to_str(dep: object) -> str:
    """Extract task_id string from a dependency dict or plain value."""
    # Use json round-trip to safely extract task_id from dict-like objects
    # without triggering ty's dict[Unknown, Unknown] narrowing issues
    s = str(dep)
    if isinstance(dep, dict):
        import json as _json

        try:
            parsed = _json.loads(_json.dumps(dep))
            if isinstance(parsed, dict) and "task_id" in parsed:
                s = str(parsed["task_id"])
        except (TypeError, ValueError):
            pass
    return s


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
        data = json.loads(result.stdout)
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
        """List task issues with optional filters."""
        cmd: list[str] = [
            "gh",
            "issue",
            "list",
            "--json",
            GH_JSON_FIELDS,
            "--state",
            status,
            "--label",
            self._task_label,
        ]
        if milestone:
            cmd.extend(["--milestone", milestone])
        for lbl in labels or []:
            cmd.extend(["--label", lbl])

        result = run_gh(cmd)
        if result.returncode != 0:
            return []

        items: list[dict] = json.loads(result.stdout)
        return [
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
        # Also fetch closed tasks to check if deps are done
        closed_details = self.list(status="closed") if state != "all" else []
        closed_ids = {d.number for d in closed_details}
        done_ids = closed_ids  # Closed = done for dependency resolution

        summaries: _list[TaskSummary] = []
        for d in details:
            deps_met = True
            if d.dependencies:
                for dep in d.dependencies:
                    dep_id = dep.task_id if isinstance(dep, Dependency) else str(dep)
                    dep_id = dep_id.lstrip("#")
                    try:
                        dep_num = int(dep_id)
                        if dep_num not in done_ids:
                            deps_met = False
                            break
                    except ValueError:
                        # Unresolvable dep = not met
                        deps_met = False
                        break
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
        """Update fields in a GitHub issue body by re-rendering the relevant lines."""
        import re

        issue_number = _extract_issue_number(task_id)

        # Reconstruct the body with updated fields
        cmd = ["gh", "issue", "view", str(issue_number), "--json", "body", "-q", ".body"]
        result = run_gh(cmd)
        check_result(result, "issue view body")
        body = result.stdout.strip()

        for key, value in fields.items():
            if key == "dependencies":
                # Replace the **Dependencies**: line
                dep_list = value if isinstance(value, list) else [value]
                dep_strs = [_dep_to_str(d) for d in dep_list]
                new_line = f"**Dependencies**: {', '.join(dep_strs)}"
                body = re.sub(r"\*\*Dependencies\*\*:.*", new_line, body)

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

        Ranked by number of dependents (descending), then by issue number.
        """
        open_tasks = self.list(status="open")
        closed_tasks = self.list(status="closed")
        closed_numbers = {d.number for d in closed_tasks}

        # Build reverse-dependency map: issue_number -> count of dependents
        dependents_count: dict[int, int] = {}
        for d in open_tasks:
            if d.dependencies:
                for dep in d.dependencies:
                    dep_id = dep.task_id if isinstance(dep, Dependency) else str(dep)
                    dep_id = dep_id.lstrip("#")
                    try:
                        dep_num = int(dep_id)
                        dependents_count[dep_num] = dependents_count.get(dep_num, 0) + 1
                    except ValueError:
                        pass

        results: _list[TaskSummary] = []
        for d in open_tasks:
            deps_met = True
            if d.dependencies:
                for dep in d.dependencies:
                    dep_id = dep.task_id if isinstance(dep, Dependency) else str(dep)
                    dep_id = dep_id.lstrip("#")
                    try:
                        dep_num = int(dep_id)
                        if dep_num not in closed_numbers:
                            deps_met = False
                            break
                    except ValueError:
                        deps_met = False
                        break
            if not deps_met:
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
        gate_lines: _list[str] = []
        for g in gates:
            gate_lines.append(f"- **{g.id}** ({g.type}): {g.description} [{g.status}]")
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
        """Compact a completed task by editing its issue body to a summary.

        Uses the same ``TaskCompactor`` logic as the local backend.
        """
        from ydk.core.compaction import TaskCompactor

        issue_number = _extract_issue_number(task_id)
        task = self.get(issue_number)
        compactor = TaskCompactor()
        compacted = compactor.compact_task(task)

        # Rewrite issue body with compacted content
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

        new_body = "\n".join(lines)
        update_cmd = ["gh", "issue", "edit", str(issue_number), "--body", new_body]
        update_result = run_gh(update_cmd)
        check_result(update_result, "issue edit body (compact)")

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


def _extract_issue_number(task_id: str) -> int:
    """Extract numeric issue number from task_id.

    Handles both 'T-001' (local format) and '42' (GitHub issue number).
    """
    task_id = task_id.lstrip("#")
    if task_id.startswith("T-") or task_id.startswith("t-"):
        return int(task_id.split("-")[1])
    return int(task_id)

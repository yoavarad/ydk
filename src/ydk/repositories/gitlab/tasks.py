"""GitLab task repository — CRUD for task issues via glab CLI."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from ydk.models.pm import AcceptanceCriterion, Dependency, TaskCreate, TaskDetail, TaskStatus, TaskSummary
from ydk.models.task import is_blocking_dependency
from ydk.repositories.github.parser import render_gate_line
from ydk.repositories.gitlab._helpers import (
    check_result,
    extract_label_names,
    glab_state_flags,
    issue_ref,
    list_glab_issues,
    load_json_stdout,
    map_status,
    run_glab,
)
from ydk.repositories.gitlab.parser import parse_body, render_body

if TYPE_CHECKING:
    import builtins

    from ydk.core.llm_provider import LLMProvider
    from ydk.models.compaction import CompactedTask
    from ydk.models.gate import Gate

logger = logging.getLogger(__name__)

_ISSUE_REF = re.compile(r"#?([0-9]+)")

# Epics and stories are plain issues too; these labels keep them out of task listings.
_NON_TASK_LABELS = frozenset({"kind:epic", "kind:story"})
# Type label every task issue carries (mirrors GitHubTaskRepository's default ``task_label``).
_TASK_LABEL = "task"


def _is_task(detail: TaskDetail) -> bool:
    """True if the issue carries the task label and is not an epic or story."""
    return _TASK_LABEL in detail.labels and not _NON_TASK_LABELS.intersection(detail.labels)


def _status_label(label: str) -> str:
    """Prefix lifecycle labels with ``status:`` to match :meth:`GitLabTaskRepository.update_status`."""
    if label in ("in-progress", "in-review") or label.startswith("blocked"):
        return f"status:{label}"
    return label


def _blocking_dep_numbers(task: TaskDetail) -> tuple[builtins.list[int], bool]:
    """Return IIDs of *task*'s blocking deps and whether any was unresolvable."""
    numbers: builtins.list[int] = []
    unresolved = False
    for dep in task.dependencies:
        if not is_blocking_dependency(dep):
            continue
        dep_id = dep.task_id if isinstance(dep, Dependency) else str(dep)
        try:
            numbers.append(int(issue_ref(dep_id)))
        except ValueError:
            logger.warning("Task #%s has unresolvable dependency %r; treating it as unmet", task.number, dep_id)
            unresolved = True
    return numbers, unresolved


class GitLabTaskRepository:
    """Manage task issues on GitLab using the ``glab`` CLI.

    All subprocess calls go through :func:`run_glab` so tests can mock a
    single seam.
    """

    # ------------------------------------------------------------------
    # Public API (satisfies TaskRepository protocol)
    # ------------------------------------------------------------------

    def create(self, task: TaskCreate) -> TaskDetail:
        """Create a GitLab issue for the task and return its detail."""
        dep_ids = [d.task_id if isinstance(d, Dependency) else d for d in task.dependencies]
        body = render_body(
            story_id=task.story_id,
            spec_refs=task.spec_refs,
            dependencies=dep_ids,
            test_strategy=task.test_strategy,
            description=task.description,
            acceptance_criteria=task.acceptance_criteria,
        )

        cmd: list[str] = [
            "glab",
            "issue",
            "create",
            "--title",
            task.title,
            "--description",
            body,
            "--no-editor",
        ]
        labels = list(dict.fromkeys([_TASK_LABEL, *task.labels]))
        cmd.extend(["--label", ",".join(labels)])
        if task.milestone:
            cmd.extend(["--milestone", task.milestone])

        result = run_glab(cmd)
        check_result(result, "issue create")

        url = result.stdout.strip().splitlines()[-1]
        # Extract issue number from URL like https://gitlab.com/owner/repo/-/issues/42
        number = int(url.rstrip("/").split("/")[-1])

        return TaskDetail(
            number=number,
            title=task.title,
            story_id=task.story_id,
            spec_refs=task.spec_refs,
            dependencies=task.dependencies,
            test_strategy=task.test_strategy,
            description=task.description,
            acceptance_criteria=task.acceptance_criteria,
            labels=labels,
            status=map_status("opened"),
            url=url,
        )

    def create_task(self, task: TaskCreate) -> TaskDetail:
        """Alias for create() -- lifecycle-compatible."""
        return self.create(task)

    def get(self, issue_number: int) -> TaskDetail:
        """Fetch a single task issue by number."""
        cmd = [
            "glab",
            "issue",
            "view",
            str(issue_number),
            "--output",
            "json",
        ]
        result = run_glab(cmd)
        check_result(result, "issue view")

        data = load_json_stdout(result, "issue view")
        return self._issue_json_to_detail(data)

    def get_task(self, task_id: str) -> TaskDetail:
        """Get task by ID string (e.g. '42', '#42'). Lifecycle-compatible alias for get()."""
        match = _ISSUE_REF.fullmatch(str(task_id).strip())
        if match is None:
            msg = f"{task_id!r} is not a GitLab issue number; remote=gitlab expects N or #N"
            raise ValueError(msg)
        return self.get(int(match.group(1)))

    def list(
        self,
        milestone: str | None = None,
        labels: builtins.list[str] | None = None,
        status: str = "open",
    ) -> builtins.list[TaskDetail]:
        """List task issues matching the given filters."""
        cmd: list[str] = [
            "glab",
            "issue",
            "list",
            "--output",
            "json",
            *glab_state_flags(status),
        ]
        if milestone:
            cmd.extend(["--milestone", milestone])
        if labels:
            cmd.extend(["--label", ",".join(labels)])

        issues = list_glab_issues(run_glab, cmd)
        return [self._issue_json_to_detail(i) for i in issues]

    def list_tasks(self, state: str = "open") -> builtins.list[TaskSummary]:
        """List tasks (epics/stories excluded) as summaries with dependency status."""
        # state="all" stays unfiltered so closed epics/stories can still satisfy dependencies.
        all_details = self.list(status=state, labels=None if state == "all" else [_TASK_LABEL])
        details = [d for d in all_details if _is_task(d)]
        # Closed = done for dependency resolution; state="all" already includes closed tasks.
        closed = (
            [d for d in all_details if d.status == TaskStatus.DONE] if state == "all" else self.list(status="closed")
        )
        done_ids = {d.number for d in closed}

        summaries: builtins.list[TaskSummary] = []
        for d in details:
            dep_nums, unresolved = _blocking_dep_numbers(d)
            summaries.append(
                TaskSummary(
                    id=str(d.number),
                    title=d.title,
                    status=d.status,
                    dependencies_met=not unresolved and all(n in done_ids for n in dep_nums),
                )
            )
        return summaries

    def list_ready(self) -> builtins.list[TaskSummary]:
        """Return open tasks whose blocking deps are all closed, ranked by dependents count."""
        open_tasks = [d for d in self.list(status="open", labels=[_TASK_LABEL]) if _is_task(d)]
        closed_numbers = {d.number for d in self.list(status="closed")}
        blocking = {d.number: _blocking_dep_numbers(d) for d in open_tasks}

        dependents_count: dict[int, int] = {}
        for dep_nums, _unresolved in blocking.values():
            for dep_num in dep_nums:
                dependents_count[dep_num] = dependents_count.get(dep_num, 0) + 1

        results: builtins.list[TaskSummary] = []
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

    def update_status(self, issue_number: int, status: str) -> None:
        """Update task status via labels and/or close/reopen."""
        if status == "done":
            # Best-effort (rc ignored, like the GitHub close path): drop stale status labels first.
            stale = ",".join(f"status:{s}" for s in ("in-review", "in-progress"))
            run_glab(["glab", "issue", "update", str(issue_number), "--unlabel", stale])
            cmd = ["glab", "issue", "close", str(issue_number)]
        elif status == "open":
            cmd = ["glab", "issue", "reopen", str(issue_number)]
        else:
            # For in_progress / blocked, use labels
            cmd = ["glab", "issue", "update", str(issue_number), "--label", f"status:{status}"]

        result = run_glab(cmd)
        check_result(result, "issue update")

    def add_comment(self, issue_number: int, comment: str) -> None:
        """Add a note to a task issue."""
        cmd = ["glab", "issue", "note", str(issue_number), "--message", comment]
        result = run_glab(cmd)
        check_result(result, "issue note")

    def add_label(self, task_id: str, label: str) -> None:
        """Add a label to the issue (status labels get the ``status:`` prefix)."""
        cmd = ["glab", "issue", "update", issue_ref(task_id), "--label", _status_label(label)]
        result = run_glab(cmd)
        check_result(result, "issue update (add label)")

    def remove_label(self, task_id: str, label: str) -> None:
        """Remove a label from the issue. Best-effort, like the GitHub backend."""
        run_glab(["glab", "issue", "update", issue_ref(task_id), "--unlabel", _status_label(label)])

    def update_gates(self, task_id: str, gates: builtins.list[Gate]) -> None:
        """Persist updated gates by rewriting the issue description's ``### Gates`` section."""
        number = issue_ref(task_id)
        result = run_glab(["glab", "issue", "view", number, "--output", "json"])
        check_result(result, "issue view")
        body = (load_json_stdout(result, "issue view").get("description") or "").strip()

        gate_lines = [render_gate_line(g) for g in gates]
        new_section = "### Gates\n" + ("\n".join(gate_lines) if gate_lines else "_No gates_")
        if "### Gates" in body:
            body = re.sub(r"### Gates\n.*?(?=\n###|\Z)", lambda _m: new_section, body, flags=re.DOTALL)
        else:
            body = body.rstrip() + "\n\n" + new_section

        update = run_glab(["glab", "issue", "update", number, "--description", body])
        check_result(update, "issue update (gates)")

    def compact_task(self, task_id: str, *, llm_provider: LLMProvider | None = None) -> CompactedTask:
        """Compact a closed task: post a summary note and add the ``archived`` label.

        The issue description is never modified (mirrors the GitHub backend).
        """
        from ydk.core.compaction import TaskCompactor

        number = int(issue_ref(task_id))
        compacted = TaskCompactor(llm_provider).compact_task(self.get(number))

        lines: builtins.list[str] = ["### Summary", compacted.summary, ""]
        if compacted.key_decisions:
            lines.append("### Key Decisions")
            lines.extend(f"- {d}" for d in compacted.key_decisions)
            lines.append("")
        if compacted.files_modified:
            lines.append("### Files Modified")
            lines.extend(f"- `{fp}`" for fp in compacted.files_modified)
            lines.append("")

        self.add_comment(number, "\n".join(lines))
        self.add_label(task_id, "archived")
        return compacted

    def compact_all_done(self, *, dry_run: bool = False, llm_provider: LLMProvider | None = None) -> builtins.list[str]:
        """Compact all closed tasks. Returns the compacted issue numbers."""
        compacted_ids: builtins.list[str] = []
        for task in self.list(status="closed"):
            if "archived" in task.labels:
                continue  # already compacted; don't re-post the summary note
            tid = str(task.number)
            if dry_run:
                compacted_ids.append(tid)
                continue
            try:
                self.compact_task(tid, llm_provider=llm_provider)
                compacted_ids.append(tid)
            except (RuntimeError, ValueError):
                logger.warning("Skipping task #%s: compaction failed", tid)
        return compacted_ids

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _issue_json_to_detail(self, data: dict) -> TaskDetail:
        """Convert glab JSON output to a TaskDetail."""
        body = data.get("description", "") or ""
        parsed = parse_body(body)

        return TaskDetail(
            number=data.get("iid", data.get("number", 0)),
            title=data.get("title", ""),
            story_id=parsed["story_id"],
            spec_refs=parsed["spec_refs"],
            dependencies=parsed["dependencies"],
            test_strategy=parsed["test_strategy"],
            description=parsed["description"],
            acceptance_criteria=[
                AcceptanceCriterion(text=ac.text, done=ac.done) for ac in parsed["acceptance_criteria"]
            ],
            labels=extract_label_names(data.get("labels", [])),
            status=map_status(data.get("state", "opened")),
            url=data.get("web_url", ""),
        )

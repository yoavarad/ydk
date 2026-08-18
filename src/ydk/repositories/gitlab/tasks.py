"""GitLab task repository — CRUD for task issues via glab CLI."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ydk.models.pm import AcceptanceCriterion, Dependency, TaskCreate, TaskDetail
from ydk.repositories.gitlab._helpers import (
    check_result,
    extract_label_names,
    glab_state,
    map_status,
    run_glab,
)
from ydk.repositories.gitlab.parser import parse_body, render_body

if TYPE_CHECKING:
    import builtins


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
        if task.labels:
            cmd.extend(["--label", ",".join(task.labels)])
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
            labels=task.labels,
            status=map_status("opened"),
            url=url,
        )

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

        data = json.loads(result.stdout)
        return self._issue_json_to_detail(data)

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
            "--state",
            glab_state(status),
        ]
        if milestone:
            cmd.extend(["--milestone", milestone])
        if labels:
            cmd.extend(["--label", ",".join(labels)])

        result = run_glab(cmd)
        if result.returncode != 0:
            return []

        try:
            issues = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

        return [self._issue_json_to_detail(i) for i in issues]

    def update_status(self, issue_number: int, status: str) -> None:
        """Update task status via labels and/or close/reopen."""
        if status == "done":
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

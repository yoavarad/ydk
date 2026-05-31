"""GitLab epic repository — CRUD for epic issues via glab CLI.

GitLab native Epics require Premium tier.  For free-tier compatibility,
epics are represented as regular issues with a ``kind:epic`` label --
the same approach used by the GitHub backend.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from odk.models.pm import EpicCreate, EpicDetail
from odk.repositories.gitlab._helpers import (
    check_result,
    extract_label_names,
    glab_state,
    map_status,
    run_glab,
)
from odk.repositories.gitlab.parser import render_body

if TYPE_CHECKING:
    import builtins


class GitLabEpicRepository:
    """Manage epic issues on GitLab using the ``glab`` CLI."""

    EPIC_LABEL = "kind:epic"

    # ------------------------------------------------------------------
    # Public API (satisfies EpicRepository protocol)
    # ------------------------------------------------------------------

    def create(self, epic: EpicCreate) -> EpicDetail:
        """Create a GitLab issue representing an epic."""
        body = render_body(description=epic.description)

        all_labels = [self.EPIC_LABEL, *epic.labels]
        cmd: list[str] = [
            "glab",
            "issue",
            "create",
            "--title",
            epic.title,
            "--description",
            body,
            "--no-editor",
            "--label",
            ",".join(all_labels),
        ]
        if epic.milestone:
            cmd.extend(["--milestone", epic.milestone])

        result = run_glab(cmd)
        check_result(result, "issue create")

        url = result.stdout.strip().splitlines()[-1]
        number = int(url.rstrip("/").split("/")[-1])

        return EpicDetail(
            number=number,
            title=epic.title,
            description=epic.description,
            labels=all_labels,
            status=map_status("opened"),
            url=url,
        )

    def get(self, issue_number: int) -> EpicDetail:
        """Fetch a single epic issue by number."""
        cmd = ["glab", "issue", "view", str(issue_number), "--output", "json"]
        result = run_glab(cmd)
        check_result(result, "issue view")

        data = json.loads(result.stdout)
        return self._issue_json_to_detail(data)

    def list(
        self,
        labels: builtins.list[str] | None = None,
        status: str = "open",
    ) -> builtins.list[EpicDetail]:
        """List epic issues (always includes the epic label filter)."""
        filter_labels = [self.EPIC_LABEL, *(labels or [])]
        cmd: list[str] = [
            "glab",
            "issue",
            "list",
            "--output",
            "json",
            "--state",
            glab_state(status),
            "--label",
            ",".join(filter_labels),
        ]

        result = run_glab(cmd)
        if result.returncode != 0:
            return []

        try:
            issues = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

        return [self._issue_json_to_detail(i) for i in issues]

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _issue_json_to_detail(self, data: dict) -> EpicDetail:
        # Epic description is the raw body (no structured parsing needed
        # beyond what the body itself contains).
        return EpicDetail(
            number=data.get("iid", data.get("number", 0)),
            title=data.get("title", ""),
            description=data.get("description", "") or "",
            labels=extract_label_names(data.get("labels", [])),
            status=map_status(data.get("state", "opened")),
            url=data.get("web_url", ""),
        )

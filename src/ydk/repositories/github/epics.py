"""GitHub-backed EpicRepository — uses the gh CLI via subprocess."""

from __future__ import annotations

import builtins
import json
from typing import TYPE_CHECKING

from ydk.repositories.github._helpers import GH_JSON_FIELDS, check_result, label_names, run_gh
from ydk.repositories.github.parser import parse_epic_detail, render_epic_body

if TYPE_CHECKING:
    from ydk.models.pm import EpicCreate, EpicDetail

_list = builtins.list


class GitHubEpicRepository:
    """EpicRepository implementation backed by GitHub Issues via gh CLI."""

    def __init__(self, epic_label: str = "epic") -> None:
        self._epic_label = epic_label

    def create(self, epic: EpicCreate) -> EpicDetail:
        """Create a GitHub issue representing an epic."""
        body = render_epic_body(epic)
        cmd: list[str] = [
            "gh",
            "issue",
            "create",
            "--title",
            epic.title,
            "--body",
            body,
            "--label",
            self._epic_label,
        ]
        for label in epic.labels:
            cmd.extend(["--label", label])
        if epic.milestone:
            cmd.extend(["--milestone", epic.milestone])

        result = run_gh(cmd)
        check_result(result, "issue create (epic)")

        url = result.stdout.strip()
        issue_number = int(url.rstrip("/").split("/")[-1])

        return parse_epic_detail(
            number=issue_number,
            title=epic.title,
            body=body,
            state="OPEN",
            labels=[self._epic_label, *epic.labels],
            url=url,
        )

    def get(self, issue_number: int) -> EpicDetail:
        """Retrieve an epic by its GitHub issue number."""
        cmd = ["gh", "issue", "view", str(issue_number), "--json", GH_JSON_FIELDS]
        result = run_gh(cmd)
        check_result(result, "issue view (epic)")
        data = json.loads(result.stdout)
        return parse_epic_detail(
            number=data["number"],
            title=data["title"],
            body=data.get("body", ""),
            state=data["state"],
            labels=label_names(data.get("labels", [])),
            url=data.get("url", ""),
        )

    def list(
        self,
        labels: _list[str] | None = None,
        status: str = "open",
    ) -> _list[EpicDetail]:
        """List epics filtered by labels and status."""
        cmd: list[str] = [
            "gh",
            "issue",
            "list",
            "--json",
            GH_JSON_FIELDS,
            "--state",
            status,
            "--label",
            self._epic_label,
        ]
        for lbl in labels or []:
            cmd.extend(["--label", lbl])

        result = run_gh(cmd)
        if result.returncode != 0:
            return []

        items: list[dict] = json.loads(result.stdout)
        return [
            parse_epic_detail(
                number=item["number"],
                title=item["title"],
                body=item.get("body", ""),
                state=item["state"],
                labels=label_names(item.get("labels", [])),
                url=item.get("url", ""),
            )
            for item in items
        ]

    # -- lifecycle-compatible aliases ----------------------------------------

    def create_epic(self, epic: EpicCreate) -> EpicDetail:
        """Alias for create() — lifecycle-compatible."""
        return self.create(epic)

    def list_epics(self, status: str = "open") -> _list[EpicDetail]:
        """List all epics — lifecycle-compatible."""
        return self.list(status=status)

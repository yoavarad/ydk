"""GitHub-backed StoryRepository — uses the gh CLI via subprocess."""

from __future__ import annotations

import builtins
import json
from typing import TYPE_CHECKING

from ydk.repositories.github._helpers import GH_JSON_FIELDS, check_result, label_names, run_gh
from ydk.repositories.github.parser import parse_story_detail, render_story_body

if TYPE_CHECKING:
    from ydk.models.pm import StoryCreate, StoryDetail

_list = builtins.list


class GitHubStoryRepository:
    """StoryRepository implementation backed by GitHub Issues via gh CLI."""

    def __init__(self, story_label: str = "story") -> None:
        self._story_label = story_label

    def create(self, story: StoryCreate) -> StoryDetail:
        """Create a GitHub issue representing a story."""
        body = render_story_body(story)
        cmd: list[str] = [
            "gh",
            "issue",
            "create",
            "--title",
            story.title,
            "--body",
            body,
            "--label",
            self._story_label,
        ]
        for label in story.labels:
            cmd.extend(["--label", label])
        if story.milestone:
            cmd.extend(["--milestone", story.milestone])

        result = run_gh(cmd)
        check_result(result, "issue create (story)")

        url = result.stdout.strip()
        issue_number = int(url.rstrip("/").split("/")[-1])

        return parse_story_detail(
            number=issue_number,
            title=story.title,
            body=body,
            state="OPEN",
            labels=[self._story_label, *story.labels],
            url=url,
        )

    def get(self, issue_number: int) -> StoryDetail:
        """Retrieve a story by its GitHub issue number."""
        cmd = ["gh", "issue", "view", str(issue_number), "--json", GH_JSON_FIELDS]
        result = run_gh(cmd)
        check_result(result, "issue view (story)")
        data = json.loads(result.stdout)
        return parse_story_detail(
            number=data["number"],
            title=data["title"],
            body=data.get("body", ""),
            state=data["state"],
            labels=label_names(data.get("labels", [])),
            url=data.get("url", ""),
        )

    def list(
        self,
        milestone: str | None = None,
        labels: _list[str] | None = None,
        status: str = "open",
    ) -> _list[StoryDetail]:
        """List stories filtered by milestone, labels, and status."""
        cmd: list[str] = [
            "gh",
            "issue",
            "list",
            "--json",
            GH_JSON_FIELDS,
            "--state",
            status,
            "--label",
            self._story_label,
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
            parse_story_detail(
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

    def create_story(self, story: StoryCreate) -> StoryDetail:
        """Alias for create() — lifecycle-compatible."""
        return self.create(story)

    def list_stories(self, epic_id: str | None = None) -> _list[StoryDetail]:
        """List stories, optionally filtered by epic label."""
        labels = [f"epic:{epic_id}"] if epic_id else None
        return self.list(labels=labels)

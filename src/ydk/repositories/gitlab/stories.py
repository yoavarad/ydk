"""GitLab story repository — CRUD for story issues via glab CLI."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ydk.models.pm import AcceptanceCriterion, StoryCreate, StoryDetail
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


class GitLabStoryRepository:
    """Manage story issues on GitLab using the ``glab`` CLI.

    Stories are regular GitLab issues with a ``kind:story`` label.
    """

    STORY_LABEL = "kind:story"

    # ------------------------------------------------------------------
    # Public API (satisfies StoryRepository protocol)
    # ------------------------------------------------------------------

    def create(self, story: StoryCreate) -> StoryDetail:
        """Create a GitLab issue for the story."""
        body = render_body(
            epic_id=story.epic_id,
            description=story.description,
            acceptance_criteria=story.acceptance_criteria,
        )

        all_labels = [self.STORY_LABEL, *story.labels]
        cmd: list[str] = [
            "glab",
            "issue",
            "create",
            "--title",
            story.title,
            "--description",
            body,
            "--no-editor",
            "--label",
            ",".join(all_labels),
        ]
        if story.milestone:
            cmd.extend(["--milestone", story.milestone])

        result = run_glab(cmd)
        check_result(result, "issue create")

        url = result.stdout.strip().splitlines()[-1]
        number = int(url.rstrip("/").split("/")[-1])

        # Normalize acceptance_criteria: str items become AcceptanceCriterion
        ac_out = [AcceptanceCriterion(text=ac) if isinstance(ac, str) else ac for ac in story.acceptance_criteria]

        return StoryDetail(
            number=number,
            title=story.title,
            epic_id=story.epic_id,
            description=story.description,
            acceptance_criteria=ac_out,
            labels=all_labels,
            status=map_status("opened"),
            url=url,
        )

    def get(self, issue_number: int) -> StoryDetail:
        """Fetch a single story issue by number."""
        cmd = ["glab", "issue", "view", str(issue_number), "--output", "json"]
        result = run_glab(cmd)
        check_result(result, "issue view")

        data = json.loads(result.stdout)
        return self._issue_json_to_detail(data)

    def list(
        self,
        milestone: str | None = None,
        labels: builtins.list[str] | None = None,
        status: str = "open",
    ) -> builtins.list[StoryDetail]:
        """List story issues (always includes the story label filter)."""
        filter_labels = [self.STORY_LABEL, *(labels or [])]
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
        if milestone:
            cmd.extend(["--milestone", milestone])

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

    def _issue_json_to_detail(self, data: dict) -> StoryDetail:
        body = data.get("description", "") or ""
        parsed = parse_body(body)

        return StoryDetail(
            number=data.get("iid", data.get("number", 0)),
            title=data.get("title", ""),
            epic_id=parsed["epic_id"],
            description=parsed["description"],
            acceptance_criteria=[
                AcceptanceCriterion(text=ac.text, done=ac.done) for ac in parsed["acceptance_criteria"]
            ],
            labels=extract_label_names(data.get("labels", [])),
            status=map_status(data.get("state", "opened")),
            url=data.get("web_url", ""),
        )

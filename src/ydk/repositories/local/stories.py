"""Local file-based story repository implementation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ydk.models.pm import (
    AcceptanceCriterion,
    StoryCreate,
    StoryDetail,
    StorySummary,
    TaskStatus,
)
from ydk.repositories.local.frontmatter import (
    append_comment,
    render_frontmatter,
    update_file_status,
)
from ydk.repositories.local.manifest import Manifest, parse_number_from_id

if TYPE_CHECKING:
    from pathlib import Path


class LocalStoryRepository:
    """Store stories as markdown files with YAML frontmatter + manifest index."""

    def __init__(self, tasks_root: Path) -> None:
        """tasks_root is the .ydk/tasks/ directory."""
        self._root = tasks_root
        self._stories_dir = tasks_root / "stories"
        self._manifest = Manifest(tasks_root)

    def create_story(self, story: StoryCreate) -> StoryDetail:
        """Generate ID, write S-NNN.md, update manifest. Returns StoryDetail."""
        story_id = self._manifest.next_story_id()
        number = parse_number_from_id(story_id)
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        ac_dicts: list[dict[str, object]] = []
        for ac in story.acceptance_criteria:
            if isinstance(ac, AcceptanceCriterion):
                ac_dicts.append({"text": ac.text, "done": ac.done})
            else:
                ac_dicts.append({"text": str(ac), "done": False})

        frontmatter: dict[str, object] = {
            "id": story_id,
            "title": story.title,
            "epic": story.epic_id,
            "status": "open",
            "spec_refs": [*story.spec_refs],
            "acceptance_criteria": ac_dicts,
            "labels": [*story.labels],
            "milestone": story.milestone,
            "created": now,
            "updated": now,
        }

        body = f"## Description\n\n{story.description}\n\n## Activity Log\n"

        self._stories_dir.mkdir(parents=True, exist_ok=True)
        file_path = self._stories_dir / f"{story_id}.md"
        file_path.write_text(render_frontmatter(frontmatter, body), encoding="utf-8")

        # Update manifest
        data = self._manifest.load()
        data["stories"][story_id] = {
            "title": story.title,
            "epic": story.epic_id,
            "status": "open",
            "tasks": [],
        }
        # Also update epic's story list if epic exists
        if story.epic_id and story.epic_id in data.get("epics", {}):
            epic = data["epics"][story.epic_id]
            if story_id not in epic.get("stories", []):
                epic.setdefault("stories", []).append(story_id)
        self._manifest.save(data)

        # Build AC list for return model
        ac_out: list[AcceptanceCriterion] = []
        for ac in story.acceptance_criteria:
            if isinstance(ac, AcceptanceCriterion):
                ac_out.append(ac)
            else:
                ac_out.append(AcceptanceCriterion(text=str(ac)))

        return StoryDetail(
            number=number,
            id=story_id,
            title=story.title,
            epic_id=story.epic_id,
            description=story.description,
            acceptance_criteria=ac_out,
            labels=[*story.labels],
            status=TaskStatus.OPEN,
            url="",
        )

    def list_stories(self, epic_id: str | None = None) -> list[StorySummary]:
        """Read manifest (fast). Optionally filter by epic."""
        data = self._manifest.load()
        results: list[StorySummary] = []
        for sid, info in data.get("stories", {}).items():
            if epic_id is not None and info.get("epic") != epic_id:
                continue
            results.append(
                StorySummary(
                    id=sid,
                    title=info["title"],
                    epic_id=info.get("epic", ""),
                    status=info.get("status", "open"),
                )
            )
        return results

    def update_status(self, story_id: str, status: str) -> None:
        """Update status in both the frontmatter file and the manifest."""
        update_file_status(
            self._stories_dir / f"{story_id}.md",
            story_id,
            status,
            self._manifest,
            "stories",
        )

    def add_comment(self, story_id: str, comment: str) -> None:
        """Append to Activity Log section with timestamp."""
        append_comment(self._stories_dir / f"{story_id}.md", comment)

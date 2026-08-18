"""Local file-based epic repository implementation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ydk.models.pm import EpicCreate, EpicDetail, TaskStatus
from ydk.repositories.local.frontmatter import (
    append_comment,
    render_frontmatter,
    update_file_status,
)
from ydk.repositories.local.manifest import Manifest, parse_number_from_id

if TYPE_CHECKING:
    from pathlib import Path


class LocalEpicRepository:
    """Store epics as markdown files with YAML frontmatter + manifest index."""

    def __init__(self, tasks_root: Path) -> None:
        """tasks_root is the .ydk/tasks/ directory."""
        self._root = tasks_root
        self._epics_dir = tasks_root / "epics"
        self._manifest = Manifest(tasks_root)

    def create_epic(self, epic: EpicCreate) -> EpicDetail:
        """Generate ID, write E-NNN.md, update manifest. Returns EpicDetail."""
        epic_id = self._manifest.next_epic_id()
        number = parse_number_from_id(epic_id)
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        frontmatter: dict[str, object] = {
            "id": epic_id,
            "title": epic.title,
            "status": "open",
            "release": epic.release,
            "spec_refs": [*epic.spec_refs],
            "labels": [*epic.labels],
            "milestone": epic.milestone,
            "created": now,
            "updated": now,
        }

        body = f"## Description\n\n{epic.description}\n\n## Activity Log\n"

        self._epics_dir.mkdir(parents=True, exist_ok=True)
        file_path = self._epics_dir / f"{epic_id}.md"
        file_path.write_text(render_frontmatter(frontmatter, body), encoding="utf-8")

        # Update manifest
        data = self._manifest.load()
        data["epics"][epic_id] = {
            "title": epic.title,
            "status": "open",
            "stories": [],
        }
        self._manifest.save(data)

        return EpicDetail(
            number=number,
            id=epic_id,
            title=epic.title,
            description=epic.description,
            labels=[*epic.labels],
            status=TaskStatus.OPEN,
            url="",
        )

    def update_status(self, epic_id: str, status: str) -> None:
        """Update status in both the frontmatter file and the manifest."""
        update_file_status(
            self._epics_dir / f"{epic_id}.md",
            epic_id,
            status,
            self._manifest,
            "epics",
        )

    def add_comment(self, epic_id: str, comment: str) -> None:
        """Append to Activity Log section with timestamp."""
        append_comment(self._epics_dir / f"{epic_id}.md", comment)

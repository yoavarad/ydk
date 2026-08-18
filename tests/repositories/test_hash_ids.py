"""Tests for collision-resistant hash-based ID generation."""

import re
from pathlib import Path

from ydk.models.pm import AcceptanceCriterion, TaskCreate
from ydk.repositories.local.manifest import Manifest, parse_number_from_id
from ydk.repositories.local.tasks import LocalTaskRepository

_HASH_ID_RE = re.compile(r"^[TSE]-[0-9a-f]{8}$")


def _make_task(**overrides: object) -> TaskCreate:
    defaults: dict[str, object] = {
        "title": "Test task",
        "story_id": "S-001",
        "spec_refs": [],
        "dependencies": [],
        "description": "A test task.",
        "acceptance_criteria": [AcceptanceCriterion(text="AC one")],
        "test_strategy": "unit",
    }
    defaults.update(overrides)
    return TaskCreate(**defaults)


class TestHashIdFormat:
    def test_task_id_format(self, tmp_path: Path) -> None:
        m = Manifest(tmp_path)
        tid = m.next_task_id()
        assert _HASH_ID_RE.match(tid), f"Expected hash ID, got {tid}"

    def test_story_id_format(self, tmp_path: Path) -> None:
        m = Manifest(tmp_path)
        sid = m.next_story_id()
        assert _HASH_ID_RE.match(sid), f"Expected hash ID, got {sid}"

    def test_epic_id_format(self, tmp_path: Path) -> None:
        m = Manifest(tmp_path)
        eid = m.next_epic_id()
        assert _HASH_ID_RE.match(eid), f"Expected hash ID, got {eid}"


class TestHashIdUniqueness:
    def test_no_collisions_across_1000_task_ids(self, tmp_path: Path) -> None:
        m = Manifest(tmp_path)
        ids = {m.next_task_id() for _ in range(1000)}
        assert len(ids) == 1000

    def test_no_collisions_across_1000_story_ids(self, tmp_path: Path) -> None:
        m = Manifest(tmp_path)
        ids = {m.next_story_id() for _ in range(1000)}
        assert len(ids) == 1000

    def test_no_collisions_across_1000_epic_ids(self, tmp_path: Path) -> None:
        m = Manifest(tmp_path)
        ids = {m.next_epic_id() for _ in range(1000)}
        assert len(ids) == 1000


class TestParseNumberFromId:
    def test_legacy_sequential_id(self) -> None:
        assert parse_number_from_id("T-001") == 1
        assert parse_number_from_id("T-042") == 42
        assert parse_number_from_id("S-005") == 5

    def test_hash_id_returns_zero(self) -> None:
        assert parse_number_from_id("T-a1b2c3") == 0
        assert parse_number_from_id("S-ff00aa") == 0

    def test_purely_numeric_hash_id(self) -> None:
        assert parse_number_from_id("T-123456") == 0


class TestTaskCreationWithHashIds:
    def test_created_task_has_hash_id(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        detail = repo.create_task(_make_task())
        assert _HASH_ID_RE.match(detail.id), f"Expected hash ID, got {detail.id}"

    def test_created_task_file_named_with_hash_id(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        detail = repo.create_task(_make_task())
        assert (tmp_path / "tasks" / f"{detail.id}.md").exists()

    def test_created_task_in_manifest(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        detail = repo.create_task(_make_task())
        data = Manifest(tmp_path).load()
        assert detail.id in data["tasks"]


class TestTaskRetrievalWithHashIds:
    def test_round_trip_create_get(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        created = repo.create_task(_make_task(title="Hash task"))
        fetched = repo.get_task(created.id)
        assert fetched.id == created.id
        assert fetched.title == "Hash task"

    def test_number_field_zero_for_hash_ids(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        created = repo.create_task(_make_task())
        fetched = repo.get_task(created.id)
        assert fetched.number == 0


class TestBackwardCompatibility:
    def test_read_legacy_task_file(self, tmp_path: Path) -> None:
        """Manually create a legacy T-001.md and ensure get_task reads it."""
        from ydk.repositories.local.frontmatter import render_frontmatter

        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir(parents=True)
        fm: dict[str, object] = {
            "id": "T-001",
            "title": "Legacy task",
            "story": "S-001",
            "status": "open",
            "assignee": None,
            "labels": [],
            "dependencies": [],
            "spec_refs": [],
            "test_strategy": "manual",
            "acceptance_criteria": [{"text": "works", "done": False}],
            "milestone": None,
            "created": "2025-01-01T00:00:00Z",
            "updated": "2025-01-01T00:00:00Z",
        }
        body = "## Description\n\nLegacy desc.\n\n## Activity Log\n"
        (tasks_dir / "T-001.md").write_text(render_frontmatter(fm, body), encoding="utf-8")
        repo = LocalTaskRepository(tmp_path)
        detail = repo.get_task("T-001")
        assert detail.id == "T-001"
        assert detail.title == "Legacy task"
        assert detail.number == 1


class TestManifestNoSequentialCounter:
    def test_manifest_does_not_increment_last_task_id(self, tmp_path: Path) -> None:
        m = Manifest(tmp_path)
        m.next_task_id()
        m.next_task_id()
        data = m.load()
        assert data["last_task_id"] == 0

"""Tests for the local file-based task repository."""

import re
from pathlib import Path

import yaml

from ydk.models.pm import AcceptanceCriterion, TaskCreate
from ydk.repositories.local.frontmatter import parse_frontmatter
from ydk.repositories.local.manifest import Manifest
from ydk.repositories.local.tasks import LocalTaskRepository

_HASH_RE = re.compile(r"^T-[0-9a-f]{8}$")


def _make_task(**overrides) -> TaskCreate:  # type: ignore[no-untyped-def]
    defaults: dict[str, object] = {
        "title": "Order validation rules",
        "story_id": "S-001",
        "spec_refs": ["orders.md#entities"],
        "dependencies": [],
        "description": "Implement order validation rules.",
        "acceptance_criteria": [
            AcceptanceCriterion(text="Insufficient balance raises INSUFFICIENT_BALANCE"),
            AcceptanceCriterion(text="Invalid symbol raises INVALID_SYMBOL"),
        ],
        "test_strategy": "Unit tests for domain validation",
    }
    defaults.update(overrides)
    return TaskCreate(**defaults)


class TestCreateTask:
    def test_generates_hash_ids(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        t1 = repo.create_task(_make_task(title="First"))
        t2 = repo.create_task(_make_task(title="Second"))
        assert _HASH_RE.match(t1.id), f"Expected hash ID, got {t1.id}"
        assert _HASH_RE.match(t2.id), f"Expected hash ID, got {t2.id}"
        assert t1.id != t2.id

    def test_writes_file_with_correct_frontmatter(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        detail = repo.create_task(_make_task())
        file_path = tmp_path / "tasks" / f"{detail.id}.md"
        assert file_path.exists()
        fm, _body = parse_frontmatter(file_path.read_text(encoding="utf-8"))
        assert fm["id"] == detail.id
        assert fm["title"] == "Order validation rules"
        assert fm["story"] == "S-001"
        assert fm["status"] == "open"
        assert fm["assignee"] is None
        assert fm["labels"] == []
        assert fm["spec_refs"] == ["orders.md#entities"]
        assert fm["test_strategy"] == "Unit tests for domain validation"

    def test_updates_manifest(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        detail = repo.create_task(_make_task())
        data = Manifest(tmp_path).load()
        assert detail.id in data["tasks"]
        assert data["tasks"][detail.id]["title"] == "Order validation rules"
        assert data["tasks"][detail.id]["status"] == "open"

    def test_updates_story_task_list_in_manifest(self, tmp_path: Path) -> None:
        """If the story exists in manifest, the task is added to its task list."""
        m = Manifest(tmp_path)
        data = m.load()
        data["stories"]["S-001"] = {"title": "Place Order", "epic": "E-001", "status": "open", "tasks": []}
        m.save(data)
        repo = LocalTaskRepository(tmp_path)
        detail = repo.create_task(_make_task(story_id="S-001"))
        refreshed = m.load()
        assert detail.id in refreshed["stories"]["S-001"]["tasks"]


class TestGetTask:
    def test_parses_frontmatter_and_body(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        created = repo.create_task(_make_task())
        detail = repo.get_task(created.id)
        assert detail.id == created.id
        assert detail.title == "Order validation rules"
        assert detail.story_id == "S-001"
        assert detail.status == "open"
        assert detail.description == "Implement order validation rules."
        assert len(detail.acceptance_criteria) == 2
        ac_texts = [ac.text for ac in detail.acceptance_criteria if isinstance(ac, AcceptanceCriterion)]
        assert "Insufficient balance raises INSUFFICIENT_BALANCE" in ac_texts
        assert detail.test_strategy == "Unit tests for domain validation"
        assert detail.labels == []


class TestListTasks:
    def test_reads_from_manifest(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        repo.create_task(_make_task(title="Task A"))
        repo.create_task(_make_task(title="Task B"))
        items = repo.list_tasks()
        assert len(items) == 2
        titles = {t.title for t in items}
        assert titles == {"Task A", "Task B"}

    def test_filters_by_state(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        repo.create_task(_make_task(title="Open Task"))
        t2 = repo.create_task(_make_task(title="Done Task"))
        repo.update_status(t2.id, "done")
        open_tasks = repo.list_tasks(state="open")
        assert len(open_tasks) == 1
        assert open_tasks[0].title == "Open Task"
        done_tasks = repo.list_tasks(state="done")
        assert len(done_tasks) == 1
        assert done_tasks[0].title == "Done Task"


class TestUpdateStatus:
    def test_changes_both_file_and_manifest(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        created = repo.create_task(_make_task())
        repo.update_status(created.id, "in_progress")
        data = Manifest(tmp_path).load()
        assert data["tasks"][created.id]["status"] == "in_progress"
        fm, _ = parse_frontmatter((tmp_path / "tasks" / f"{created.id}.md").read_text(encoding="utf-8"))
        assert fm["status"] == "in_progress"


class TestAddComment:
    def test_appends_to_activity_log(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        created = repo.create_task(_make_task())
        repo.add_comment(created.id, "Exploration complete.")
        content = (tmp_path / "tasks" / f"{created.id}.md").read_text(encoding="utf-8")
        assert "Exploration complete." in content
        assert "### 20" in content

    def test_timestamp_includes_utc_label(self, tmp_path: Path) -> None:
        """Activity log timestamps include (UTC) label."""
        repo = LocalTaskRepository(tmp_path)
        created = repo.create_task(_make_task())
        repo.add_comment(created.id, "Progress update.")
        content = (tmp_path / "tasks" / f"{created.id}.md").read_text(encoding="utf-8")
        assert "(UTC)" in content


class TestAddRemoveLabel:
    def test_add_label(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        created = repo.create_task(_make_task())
        repo.add_label(created.id, "bug")
        detail = repo.get_task(created.id)
        assert "bug" in detail.labels

    def test_add_label_idempotent(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        created = repo.create_task(_make_task())
        repo.add_label(created.id, "bug")
        repo.add_label(created.id, "bug")
        detail = repo.get_task(created.id)
        assert detail.labels.count("bug") == 1

    def test_remove_label(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        created = repo.create_task(_make_task())
        repo.add_label(created.id, "bug")
        repo.remove_label(created.id, "bug")
        detail = repo.get_task(created.id)
        assert "bug" not in detail.labels


class TestAssign:
    def test_updates_assignee(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        created = repo.create_task(_make_task())
        repo.assign(created.id, "agent-1")
        detail = repo.get_task(created.id)
        assert detail.assignee == "agent-1"


class TestCheckDependencies:
    def test_returns_correct_status(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        t1 = repo.create_task(_make_task(title="Dep task"))
        t2 = repo.create_task(_make_task(title="Main task", dependencies=[t1.id]))
        deps = repo.check_dependencies(t2.id)
        assert len(deps) == 1
        assert deps[0].task_id == t1.id
        assert deps[0].resolved is False
        repo.update_status(t1.id, "done")
        deps = repo.check_dependencies(t2.id)
        assert deps[0].resolved is True


class TestRoundTrip:
    def test_create_get_fields_match(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        task_data = _make_task(
            title="Round trip test",
            dependencies=["T-999"],
            description="Full round trip.",
            acceptance_criteria=[AcceptanceCriterion(text="AC one"), AcceptanceCriterion(text="AC two")],
        )
        detail_created = repo.create_task(task_data)
        detail = repo.get_task(detail_created.id)
        assert detail.id == detail_created.id
        assert detail.title == "Round trip test"
        assert detail.story_id == "S-001"
        assert detail.dependencies == ["T-999"]
        assert detail.description == "Full round trip."
        ac_texts = [ac.text for ac in detail.acceptance_criteria if isinstance(ac, AcceptanceCriterion)]
        assert ac_texts == ["AC one", "AC two"]
        assert detail.test_strategy == "Unit tests for domain validation"
        assert detail.status == "open"


class TestManifestSurvivesMultipleCreates:
    def test_ten_tasks_all_in_manifest(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        details = [repo.create_task(_make_task(title=f"Task {i}")) for i in range(10)]
        data = Manifest(tmp_path).load()
        for d in details:
            assert d.id in data["tasks"]

    def test_manifest_file_is_valid_yaml(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        for i in range(5):
            repo.create_task(_make_task(title=f"Task {i}"))
        raw = (tmp_path / "manifest.yaml").read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw)
        assert parsed is not None
        assert len(parsed["tasks"]) == 5

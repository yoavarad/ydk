"""Integration tests for ``ydk.core.migrate`` (local -> GitHub).

Source: real local repositories under ``tmp_path``. Target: real GitHub
repositories whose ``gh`` CLI boundary (``run_gh``) is replaced by a
stateful in-memory fake.
"""

from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from ydk.core.migrate import PENDING_FILE_NAME, migrate_to_github
from ydk.core.task_ref import resolve_task_ref
from ydk.models.gate import Gate, GateType
from ydk.models.pm import Dependency, DependencyType, EpicCreate, StoryCreate, TaskCreate, TaskStatus
from ydk.repositories.github.epics import GitHubEpicRepository
from ydk.repositories.github.stories import GitHubStoryRepository
from ydk.repositories.github.tasks import GitHubTaskRepository
from ydk.repositories.local.epics import LocalEpicRepository
from ydk.repositories.local.stories import LocalStoryRepository
from ydk.repositories.local.tasks import LocalTaskRepository

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class FakeGh:
    """Minimal stateful stand-in for the ``gh`` CLI (issues + labels)."""

    def __init__(self) -> None:
        self.issues: dict[int, dict] = {}
        self.calls: list[list[str]] = []
        self._next = 100
        self.fail_once: str | None = None  # first ``gh issue <verb>`` call with this verb fails once

    @staticmethod
    def _ok(stdout: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, stdout, "")

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        head = cmd[:3]
        if self.fail_once and head == ["gh", "issue", self.fail_once]:
            self.fail_once = None
            return subprocess.CompletedProcess([], 1, "", "HTTP 502")
        if head == ["gh", "label", "create"]:
            return self._ok()
        if head == ["gh", "issue", "create"]:
            number = self._next
            self._next += 1
            labels = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--label"]
            self.issues[number] = {
                "number": number,
                "title": cmd[cmd.index("--title") + 1],
                "body": cmd[cmd.index("--body") + 1],
                "state": "OPEN",
                "labels": [{"name": lbl} for lbl in labels],
                "url": f"https://github.com/o/r/issues/{number}",
            }
            return self._ok(self.issues[number]["url"] + "\n")
        if head == ["gh", "issue", "view"]:
            issue = self.issues[int(cmd[3].lstrip("#"))]
            if "-q" in cmd:
                return self._ok(issue["body"])
            return self._ok(json.dumps(issue))
        if head == ["gh", "issue", "edit"]:
            issue = self.issues[int(cmd[3].lstrip("#"))]
            if "--body" in cmd:
                issue["body"] = cmd[cmd.index("--body") + 1]
            if "--add-label" in cmd:
                issue["labels"].append({"name": cmd[cmd.index("--add-label") + 1]})
            return self._ok()
        if head == ["gh", "issue", "close"]:
            self.issues[int(cmd[3].lstrip("#"))]["state"] = "CLOSED"
            return self._ok()
        raise AssertionError(f"unexpected gh call: {cmd}")

    def created(self) -> int:
        return sum(1 for c in self.calls if c[:3] == ["gh", "issue", "create"])


@contextmanager
def _gh(fake: FakeGh) -> Iterator[None]:
    with (
        patch("ydk.repositories.github.tasks.run_gh", side_effect=fake),
        patch("ydk.repositories.github.stories.run_gh", side_effect=fake),
        patch("ydk.repositories.github.epics.run_gh", side_effect=fake),
    ):
        yield


def _seed(root: Path) -> dict[str, str]:
    """Create a local epic/story/task graph and return its local IDs."""
    epic = LocalEpicRepository(root).create_epic(EpicCreate(title="Epic A", description="epic body"))
    stories = LocalStoryRepository(root)
    story = stories.create_story(StoryCreate(title="Story A", epic_id=epic.id, description="story body"))
    tasks = LocalTaskRepository(root)
    # t_last is created first but depends on the others -> forces dependency ordering.
    base = tasks.create_task(TaskCreate(title="Base", story_id=story.id, description="base body"))
    validator = tasks.create_task(TaskCreate(title="Validator", story_id=story.id))
    gate = Gate(id="g1", type=GateType.HUMAN, description="sign-off")
    top = tasks.create_task(
        TaskCreate(
            title="Top",
            story_id=story.id,
            acceptance_criteria=["works"],
            test_strategy="unit",
            gates=[gate],
            dependencies=[
                Dependency(task_id=base.id),
                Dependency(task_id=validator.id, type=DependencyType.VALIDATES),
            ],
        )
    )
    tasks.update_status(base.id, "done")
    tasks.update_status(top.id, "in-progress")
    tasks.update_frontmatter(top.id, {"tdd_stage": "green"})
    LocalEpicRepository(root).update_status(epic.id, "done")
    return {"epic": epic.id, "story": story.id, "base": base.id, "validator": validator.id, "top": top.id}


def _migrate(root: Path, mapping: Path, *, dry_run: bool = False) -> list:
    return migrate_to_github(
        root,
        mapping,
        epic_repo=GitHubEpicRepository(),
        story_repo=GitHubStoryRepository(),
        task_repo=GitHubTaskRepository(),
        dry_run=dry_run,
    )


def test_dry_run_plans_everything_and_creates_nothing(tmp_path: Path) -> None:
    root = tmp_path / ".ydk"
    ids = _seed(root)
    mapping = root / "batch-mapping.json"
    fake = FakeGh()
    with _gh(fake):
        plan = _migrate(root, mapping, dry_run=True)
    assert fake.calls == []
    assert not mapping.exists()
    assert [(p.kind, p.local_id, p.action) for p in plan][:2] == [
        ("epic", ids["epic"], "create"),
        ("story", ids["story"], "create"),
    ]
    task_order = [p.local_id for p in plan if p.kind == "task"]
    assert set(task_order) == {ids["base"], ids["validator"], ids["top"]}
    assert task_order.index(ids["top"]) > task_order.index(ids["base"])
    assert task_order.index(ids["top"]) > task_order.index(ids["validator"])


def test_migrate_preserves_links_statuses_deps_gates_and_tdd_stage(tmp_path: Path) -> None:
    root = tmp_path / ".ydk"
    ids = _seed(root)
    mapping = root / "batch-mapping.json"
    fake = FakeGh()
    with _gh(fake):
        _migrate(root, mapping)
        id_map = json.loads(mapping.read_text(encoding="utf-8"))
        assert set(id_map) == set(ids.values())
        num = {k: resolve_task_ref(v, mapping) for k, v in ids.items()}

        story = GitHubStoryRepository().get(int(num["story"]))
        assert story.epic_id == f"#{num['epic']}"
        assert fake.issues[int(num["epic"])]["state"] == "CLOSED"

        top = GitHubTaskRepository().get(int(num["top"]))
        assert top.story_id == f"#{num['story']}"
        assert top.status == TaskStatus.IN_PROGRESS
        assert top.tdd_stage == "green"
        assert [g.id for g in top.gates] == ["g1"]
        assert top.test_strategy == "unit"
        assert {(d.task_id, d.type) for d in top.dependencies if isinstance(d, Dependency)} == {
            (f"#{num['base']}", DependencyType.BLOCKS),
            (f"#{num['validator']}", DependencyType.VALIDATES),
        }

        base = GitHubTaskRepository().get(int(num["base"]))
        assert base.status == TaskStatus.DONE
        assert base.description == "base body"


def test_second_run_creates_nothing_new(tmp_path: Path) -> None:
    root = tmp_path / ".ydk"
    _seed(root)
    mapping = root / "batch-mapping.json"
    fake = FakeGh()
    with _gh(fake):
        _migrate(root, mapping)
        first = fake.created()
        before = mapping.read_text(encoding="utf-8")
        plan = _migrate(root, mapping)
    assert first == 5
    assert fake.created() == first
    assert all(p.action == "skip" for p in plan)
    assert mapping.read_text(encoding="utf-8") == before


def test_existing_mapping_entries_are_kept(tmp_path: Path) -> None:
    root = tmp_path / ".ydk"
    _seed(root)
    mapping = root / "batch-mapping.json"
    mapping.write_text(json.dumps({"placeholder-x": "#7"}), encoding="utf-8")
    fake = FakeGh()
    with _gh(fake):
        _migrate(root, mapping)
    assert json.loads(mapping.read_text(encoding="utf-8"))["placeholder-x"] == "#7"


def test_local_labels_are_added_on_github(tmp_path: Path) -> None:
    root = tmp_path / ".ydk"
    task = LocalTaskRepository(root).create_task(TaskCreate(title="Labelled", labels=["backend"]))
    mapping = root / "batch-mapping.json"
    fake = FakeGh()
    with _gh(fake):
        _migrate(root, mapping)
        number = int(resolve_task_ref(task.id, mapping))
        assert "backend" in GitHubTaskRepository().get(number).labels


def test_dependency_cycle_is_rewritten_in_second_pass(tmp_path: Path) -> None:
    root = tmp_path / ".ydk"
    tasks = LocalTaskRepository(root)
    first = tasks.create_task(TaskCreate(title="First"))
    second = tasks.create_task(TaskCreate(title="Second", dependencies=[Dependency(task_id=first.id)]))
    tasks.update_frontmatter(first.id, {"dependencies": [{"task_id": second.id, "type": "related"}]})
    mapping = root / "batch-mapping.json"
    fake = FakeGh()
    with _gh(fake):
        _migrate(root, mapping)
        n_first = resolve_task_ref(first.id, mapping)
        n_second = resolve_task_ref(second.id, mapping)
        deps_first = GitHubTaskRepository().get(int(n_first)).dependencies
        deps_second = GitHubTaskRepository().get(int(n_second)).dependencies
    assert deps_first == [Dependency(task_id=f"#{n_second}", type=DependencyType.RELATED)]
    assert deps_second == [Dependency(task_id=f"#{n_first}")]


@pytest.mark.parametrize("failing_verb", ["close", "edit"])
def test_rerun_after_post_create_failure_finalizes_without_duplicates(tmp_path: Path, failing_verb: str) -> None:
    root = tmp_path / ".ydk"
    ids = _seed(root)
    mapping = root / "batch-mapping.json"
    fake = FakeGh()
    fake.fail_once = failing_verb
    with _gh(fake):
        with pytest.raises(RuntimeError):
            _migrate(root, mapping)
        assert (root / PENDING_FILE_NAME).exists()
        plan = _migrate(root, mapping)
        assert fake.created() == 5
        assert "finalize" in {p.action for p in plan}
        assert not (root / PENDING_FILE_NAME).exists()
        num = {k: int(resolve_task_ref(v, mapping)) for k, v in ids.items()}
        assert fake.issues[num["epic"]]["state"] == "CLOSED"
        assert GitHubTaskRepository().get(num["base"]).status == TaskStatus.DONE
        top = GitHubTaskRepository().get(num["top"])
        assert top.status == TaskStatus.IN_PROGRESS
        assert top.tdd_stage == "green"


def test_pending_entry_missing_from_mapping_is_finalized_not_recreated(tmp_path: Path) -> None:
    """A crash between the pending-file write and the mapping write must not duplicate the issue."""
    root = tmp_path / ".ydk"
    task = LocalTaskRepository(root).create_task(TaskCreate(title="Half-done"))
    LocalTaskRepository(root).update_status(task.id, "done")
    mapping = root / "batch-mapping.json"
    fake = FakeGh()
    with _gh(fake):
        number = GitHubTaskRepository().create_task(TaskCreate(title="Half-done")).number
        (root / PENDING_FILE_NAME).write_text(json.dumps({task.id: f"#{number}"}), encoding="utf-8")
        plan = _migrate(root, mapping)
    assert fake.created() == 1
    assert [p.action for p in plan] == ["finalize"]
    assert json.loads(mapping.read_text(encoding="utf-8")) == {task.id: f"#{number}"}
    assert fake.issues[number]["state"] == "CLOSED"
    assert not (root / PENDING_FILE_NAME).exists()

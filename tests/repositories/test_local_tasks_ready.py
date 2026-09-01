"""Tests for list_ready() — returns all actionable tasks with satisfied dependencies."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ydk.models.pm import Dependency, DependencyType, TaskCreate

if TYPE_CHECKING:
    from pathlib import Path
from ydk.repositories.local.tasks import LocalTaskRepository


def _make_task(**overrides: object) -> TaskCreate:
    defaults: dict[str, object] = {
        "title": "Test task",
        "story_id": "S-001",
        "spec_refs": [],
        "dependencies": [],
        "description": "A test task.",
        "acceptance_criteria": [],
        "test_strategy": "",
    }
    defaults.update(overrides)
    return TaskCreate(**defaults)


class TestListReadyEmpty:
    def test_no_tasks_returns_empty(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        assert repo.list_ready() == []


class TestListReadyDepsMet:
    def test_task_with_all_deps_done_appears(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        dep = repo.create_task(_make_task(title="Dependency"))
        repo.update_status(dep.id, "done")
        main = repo.create_task(_make_task(title="Main", dependencies=[dep.id]))
        ready = repo.list_ready()
        ids = [t.id for t in ready]
        assert main.id in ids

    def test_task_with_no_deps_appears(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        t = repo.create_task(_make_task(title="Independent"))
        ready = repo.list_ready()
        assert len(ready) == 1
        assert ready[0].id == t.id


class TestListReadyDepsPending:
    def test_task_with_pending_blocking_dep_excluded(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        dep = repo.create_task(_make_task(title="Dependency"))
        main = repo.create_task(_make_task(title="Main", dependencies=[dep.id]))
        ready = repo.list_ready()
        ids = [t.id for t in ready]
        assert main.id not in ids
        # The dependency itself has no deps, so it should be ready
        assert dep.id in ids

    def test_task_with_pending_waits_for_dep_excluded(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        dep = repo.create_task(_make_task(title="Dependency"))
        waits_dep = Dependency(task_id=dep.id, type=DependencyType.WAITS_FOR)
        main = repo.create_task(_make_task(title="Main", dependencies=[waits_dep]))
        ready = repo.list_ready()
        ids = [t.id for t in ready]
        assert main.id not in ids

    def test_task_with_pending_conditional_blocks_dep_excluded(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        dep = repo.create_task(_make_task(title="Dependency"))
        cond_dep = Dependency(task_id=dep.id, type=DependencyType.CONDITIONAL_BLOCKS)
        main = repo.create_task(_make_task(title="Main", dependencies=[cond_dep]))
        ready = repo.list_ready()
        ids = [t.id for t in ready]
        assert main.id not in ids


class TestListReadyNonBlockingIgnored:
    def test_validates_dep_does_not_block(self, tmp_path: Path) -> None:
        """Non-blocking dependency types like 'validates' should not prevent readiness."""
        repo = LocalTaskRepository(tmp_path)
        dep = repo.create_task(_make_task(title="Dependency"))
        validates_dep = Dependency(task_id=dep.id, type=DependencyType.VALIDATES)
        main = repo.create_task(_make_task(title="Main", dependencies=[validates_dep]))
        ready = repo.list_ready()
        ids = [t.id for t in ready]
        assert main.id in ids

    def test_related_dep_does_not_block(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        dep = repo.create_task(_make_task(title="Dependency"))
        related_dep = Dependency(task_id=dep.id, type=DependencyType.RELATED)
        main = repo.create_task(_make_task(title="Main", dependencies=[related_dep]))
        ready = repo.list_ready()
        ids = [t.id for t in ready]
        assert main.id in ids


class TestListReadyExcludesNonOpen:
    def test_in_progress_excluded(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        t = repo.create_task(_make_task(title="In progress"))
        repo.update_status(t.id, "in-progress")
        ready = repo.list_ready()
        assert len(ready) == 0

    def test_done_excluded(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        t = repo.create_task(_make_task(title="Done"))
        repo.update_status(t.id, "done")
        ready = repo.list_ready()
        assert len(ready) == 0

    def test_blocked_excluded(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        t = repo.create_task(_make_task(title="Blocked"))
        repo.update_status(t.id, "blocked-by-code")
        ready = repo.list_ready()
        assert len(ready) == 0


class TestListReadyFrontmatterSourceOfTruth:
    def test_stale_manifest_status_ignored_in_favor_of_frontmatter(self, tmp_path: Path) -> None:
        """Hand-edited frontmatter status must win over stale manifest cache."""
        repo = LocalTaskRepository(tmp_path)
        t = repo.create_task(_make_task(title="Hand-edited"))

        # Simulate an out-of-band edit: frontmatter says done, manifest still says open.
        file_path = tmp_path / "tasks" / f"{t.id}.md"
        content = file_path.read_text(encoding="utf-8")
        content = content.replace("status: open", "status: done")
        file_path.write_text(content, encoding="utf-8")

        ready = repo.list_ready()
        assert t.id not in [r.id for r in ready]

        done_tasks = repo.list_tasks(state="done")
        assert t.id in [d.id for d in done_tasks]


class TestListReadyRanking:
    def test_ranked_by_dependent_count_descending(self, tmp_path: Path) -> None:
        """Tasks with more dependents (tasks that depend on them) rank higher."""
        repo = LocalTaskRepository(tmp_path)
        popular = repo.create_task(_make_task(title="Popular"))
        lonely = repo.create_task(_make_task(title="Lonely"))

        # Create 3 tasks that depend on 'popular'
        for i in range(3):
            repo.create_task(_make_task(title=f"Dep-of-popular-{i}", dependencies=[popular.id]))

        # Create 1 task that depends on 'lonely'
        repo.create_task(_make_task(title="Dep-of-lonely", dependencies=[lonely.id]))

        ready = repo.list_ready()
        ready_ids = [t.id for t in ready]

        # Both should be ready (they have no deps themselves)
        assert popular.id in ready_ids
        assert lonely.id in ready_ids

        # Popular should rank before lonely
        popular_idx = ready_ids.index(popular.id)
        lonely_idx = ready_ids.index(lonely.id)
        assert popular_idx < lonely_idx

    def test_dependents_count_populated(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        popular = repo.create_task(_make_task(title="Popular"))
        for i in range(2):
            repo.create_task(_make_task(title=f"Dep-{i}", dependencies=[popular.id]))
        ready = repo.list_ready()
        popular_task = next(t for t in ready if t.id == popular.id)
        assert popular_task.dependents_count == 2

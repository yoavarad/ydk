"""Tests for ydk.core.rollup -- story/epic auto-close when their last task is done."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import pytest

from ydk.core.rollup import rollup_task_done
from ydk.models.pm import EpicCreate, StoryCreate, TaskCreate
from ydk.repositories.github.epics import GitHubEpicRepository
from ydk.repositories.github.stories import GitHubStoryRepository
from ydk.repositories.github.tasks import GitHubTaskRepository
from ydk.repositories.local.epics import LocalEpicRepository
from ydk.repositories.local.stories import LocalStoryRepository
from ydk.repositories.local.tasks import LocalTaskRepository

if TYPE_CHECKING:
    from pathlib import Path


class _Local:
    """Real local repositories sharing one tmp_path root, seeded with E-001 > S-001 (T1, T2), S-002 (T3)."""

    def __init__(self, root: Path) -> None:
        self.tasks = LocalTaskRepository(root)
        self.stories = LocalStoryRepository(root)
        self.epics = LocalEpicRepository(root)
        self.epic = self.epics.create_epic(EpicCreate(title="Ship it")).id
        self.s1 = self.stories.create_story(StoryCreate(title="Story one", epic_id=self.epic)).id
        self.s2 = self.stories.create_story(StoryCreate(title="Story two", epic_id=self.epic)).id
        self.t1 = self.tasks.create_task(TaskCreate(title="t1", story_id=self.s1)).id
        self.t2 = self.tasks.create_task(TaskCreate(title="t2", story_id=self.s1)).id
        self.t3 = self.tasks.create_task(TaskCreate(title="t3", story_id=self.s2)).id

    def done(self, task_id: str) -> list[str]:
        self.tasks.update_status(task_id, "done")
        return rollup_task_done(task_id, self.tasks, self.stories, self.epics)

    def story_status(self, story_id: str) -> str:
        return next(s.status for s in self.stories.list_stories() if s.id == story_id)

    def epic_status(self) -> str:
        return next(e.status for e in self.epics.list_epics(status="all") if e.id == self.epic)


@pytest.fixture
def local(tmp_path: Path) -> _Local:
    return _Local(tmp_path / ".ydk")


class TestLocalRollup:
    def test_not_last_task_changes_nothing(self, local: _Local) -> None:
        assert local.done(local.t1) == []
        assert local.story_status(local.s1) == "open"
        assert local.epic_status() == "open"

    def test_last_task_in_story_closes_story_only(self, local: _Local) -> None:
        local.done(local.t1)
        messages = local.done(local.t2)
        assert local.story_status(local.s1) == "done"
        assert local.story_status(local.s2) == "open"
        assert local.epic_status() == "open"
        assert messages == [f'Story {local.s1} "Story one" complete (2/2 tasks)']

    def test_last_task_in_epic_closes_story_and_epic(self, local: _Local) -> None:
        local.done(local.t1)
        local.done(local.t2)
        messages = local.done(local.t3)
        assert local.story_status(local.s2) == "done"
        assert local.epic_status() == "done"
        assert f'Epic {local.epic} "Ship it" complete (3/3 tasks)' in messages
        assert messages[-1] == f"Next: ydk memory retrospective --epic {local.epic}"

    def test_epic_waits_for_open_tasks_in_other_stories(self, local: _Local) -> None:
        local.done(local.t3)
        local.done(local.t1)
        assert local.epic_status() == "open"
        messages = local.done(local.t2)
        assert local.epic_status() == "done"
        assert any(m.startswith(f"Epic {local.epic}") for m in messages)

    def test_rerun_after_complete_is_silent(self, local: _Local) -> None:
        for t in (local.t1, local.t2, local.t3):
            local.done(t)
        assert rollup_task_done(local.t3, local.tasks, local.stories, local.epics) == []

    def test_task_without_story_is_noop(self, local: _Local) -> None:
        orphan = local.tasks.create_task(TaskCreate(title="orphan")).id
        assert local.done(orphan) == []
        assert local.story_status(local.s1) == "open"
        assert local.epic_status() == "open"

    def test_story_without_epic_closes_story_only(self, local: _Local) -> None:
        lone = local.stories.create_story(StoryCreate(title="Lone")).id
        task = local.tasks.create_task(TaskCreate(title="t", story_id=lone)).id
        assert local.done(task) == [f'Story {lone} "Lone" complete (1/1 tasks)']
        assert local.story_status(lone) == "done"
        assert local.epic_status() == "open"

    def test_unknown_task_is_noop(self, local: _Local) -> None:
        assert rollup_task_done("T-999", local.tasks, local.stories, local.epics) == []


class _FakeGh:
    """Stand-in for the gh CLI (system boundary): serves issue lists and records closes."""

    def __init__(self, issues: list[dict[str, object]]) -> None:
        self.issues = issues
        self.closed: list[str] = []

    def __call__(self, cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "issue", "list"]:
            label = cmd[cmd.index("--label") + 1]
            items = [i for i in self.issues if label in [lbl["name"] for lbl in i["labels"]]]  # ty: ignore[not-iterable]
            return subprocess.CompletedProcess(cmd, 0, json.dumps(items), "")
        if cmd[:3] == ["gh", "issue", "close"]:
            self.closed.append(cmd[3])
            for issue in self.issues:
                if str(issue["number"]) == cmd[3]:
                    issue["state"] = "CLOSED"
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"unexpected gh call: {cmd}")


def _issue(number: int, title: str, label: str, body: str = "", state: str = "OPEN") -> dict[str, object]:
    return {
        "number": number,
        "title": title,
        "state": state,
        "labels": [{"name": label}],
        "body": body,
        "url": f"https://github.com/o/r/issues/{number}",
    }


class TestGitHubRollup:
    def test_last_task_closes_story_and_epic_via_gh(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gh = _FakeGh(
            [
                _issue(1, "Epic", "epic"),
                _issue(2, "Story", "story", "**Epic**: #1"),
                _issue(3, "done task", "task", "**Story**: #2", state="CLOSED"),
                _issue(4, "last task", "task", "**Story**: #2", state="CLOSED"),
            ]
        )
        monkeypatch.setattr(subprocess, "run", gh)
        messages = rollup_task_done("4", GitHubTaskRepository(), GitHubStoryRepository(), GitHubEpicRepository())
        assert gh.closed == ["2", "1"]
        assert 'Epic 1 "Epic" complete (2/2 tasks)' in messages
        assert messages[-1] == "Next: ydk memory retrospective --epic 1"

    def test_not_last_task_closes_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gh = _FakeGh(
            [
                _issue(1, "Epic", "epic"),
                _issue(2, "Story", "story", "**Epic**: #1"),
                _issue(3, "open task", "task", "**Story**: #2"),
                _issue(4, "closed task", "task", "**Story**: #2", state="CLOSED"),
            ]
        )
        monkeypatch.setattr(subprocess, "run", gh)
        assert rollup_task_done("4", GitHubTaskRepository(), GitHubStoryRepository(), GitHubEpicRepository()) == []
        assert gh.closed == []

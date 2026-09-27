"""GitHub story -> epic linkage: list_stories(epic_id) filters on the parsed **Epic** body field."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from ydk.models.pm import EpicCreate, StoryCreate
from ydk.repositories.github.epics import GitHubEpicRepository
from ydk.repositories.github.stories import GitHubStoryRepository


def _ok(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _issue(number: int, body: str, labels: list[str] | None = None) -> dict:
    return {
        "number": number,
        "title": f"Story {number}",
        "state": "OPEN",
        "labels": [{"name": n} for n in (labels or ["story"])],
        "body": body,
        "url": f"https://github.com/o/r/issues/{number}",
    }


class _FakeGh:
    """Minimal in-memory gh CLI: `issue create` stores bodies, `issue list` returns them."""

    def __init__(self) -> None:
        self.issues: list[dict] = []

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "issue", "create"]:
            number = 100 + len(self.issues)
            body = cmd[cmd.index("--body") + 1]
            labels = [cmd[i + 1] for i, c in enumerate(cmd) if c == "--label"]
            self.issues.append(_issue(number, body, labels))
            return _ok(f"https://github.com/o/r/issues/{number}\n")
        if cmd[:3] == ["gh", "issue", "list"]:
            return _ok(json.dumps(self.issues))
        if cmd[:3] == ["gh", "issue", "view"]:
            number = int(cmd[3])
            return _ok(json.dumps(next(i for i in self.issues if i["number"] == number)))
        raise AssertionError(f"unexpected gh call: {cmd}")


@pytest.mark.parametrize("epic_ref", ["5", "#5", "E-005"])
def test_story_created_with_epic_is_listed_under_that_epic(epic_ref: str) -> None:
    fake = _FakeGh()
    repo = GitHubStoryRepository()
    with patch("ydk.repositories.github.stories.run_gh", side_effect=fake):
        created = repo.create_story(StoryCreate(title="In epic 5", epic_id="5"))
        repo.create_story(StoryCreate(title="In epic 6", epic_id="6"))
        repo.create_story(StoryCreate(title="No epic"))
        stories = repo.list_stories(epic_id=epic_ref)
    assert [s.number for s in stories] == [created.number]


def test_list_stories_without_epic_returns_all() -> None:
    fake = _FakeGh()
    fake.issues = [_issue(1, "**Epic**: #5"), _issue(2, "")]
    with patch("ydk.repositories.github.stories.run_gh", side_effect=fake):
        stories = GitHubStoryRepository().list_stories()
    assert [s.number for s in stories] == [1, 2]


def test_list_stories_does_not_filter_by_epic_label() -> None:
    fake = _FakeGh()
    fake.issues = [_issue(1, "**Epic**: #5")]
    with patch("ydk.repositories.github.stories.run_gh", side_effect=fake) as mock_run:
        GitHubStoryRepository().list_stories(epic_id="5")
    cmd = mock_run.call_args[0][0]
    assert "epic:5" not in cmd


def test_story_refs_survive_create_then_get() -> None:
    fake = _FakeGh()
    repo = GitHubStoryRepository()
    with patch("ydk.repositories.github.stories.run_gh", side_effect=fake):
        created = repo.create(StoryCreate(title="S", spec_refs=["a.md#x"], component_refs=["svc"]))
        fetched = repo.get(created.number)
    assert fetched.spec_refs == ["a.md#x"]
    assert fetched.component_refs == ["svc"]


def test_epic_refs_survive_create_then_get() -> None:
    fake = _FakeGh()
    repo = GitHubEpicRepository()
    with patch("ydk.repositories.github.epics.run_gh", side_effect=fake):
        created = repo.create(EpicCreate(title="E", release="v2", spec_refs=["a.md#x", "b.md"]))
        fetched = repo.get(created.number)
    assert fetched.release == "v2"
    assert fetched.spec_refs == ["a.md#x", "b.md"]

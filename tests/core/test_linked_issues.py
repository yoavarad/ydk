"""Tests for ydk.core.linked_issues. gh is faked at the subprocess boundary."""

from __future__ import annotations

import json
import subprocess

import pytest

from ydk.core import linked_issues
from ydk.core.linked_issues import MARKER_PREFIX


class FakeGh:
    """Records gh invocations; responses map an argv prefix (tuple) to stdout text."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.responses: dict[tuple[str, ...], str] = {}
        self.fail_on: tuple[str, ...] | None = None

    def __call__(self, argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        args = tuple(argv[1:])
        self.calls.append(args)
        if self.fail_on and args[: len(self.fail_on)] == self.fail_on:
            return subprocess.CompletedProcess(argv, 1, "", "boom")
        for prefix, out in self.responses.items():
            if args[: len(prefix)] == prefix:
                return subprocess.CompletedProcess(argv, 0, out, "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def wrote(self, *prefix: str) -> list[tuple[str, ...]]:
        return [c for c in self.calls if c[: len(prefix)] == prefix]


@pytest.fixture
def fake_gh(monkeypatch: pytest.MonkeyPatch) -> FakeGh:
    fake = FakeGh()
    monkeypatch.setattr(subprocess, "run", fake)
    return fake


def comments_json(*bodies: str) -> str:
    return json.dumps({"comments": [{"body": b} for b in bodies]})


def marker(kind: str, issue: int, extra: str = "") -> str:
    tail = f" {extra}" if extra else ""
    return f"{MARKER_PREFIX}:{kind} issue={issue}{tail} -->"


def setup_issue(fake_gh: FakeGh, task_states: dict[str, str]) -> None:
    fake_gh.responses[("issue", "list")] = json.dumps([{"number": 3}])
    fake_gh.responses[("issue", "view", "3", "--json", "comments")] = comments_json(
        marker("link", 3, f"tasks={','.join(task_states)}")
    )
    fake_gh.responses[("issue", "view", "3", "--json", "state")] = json.dumps({"state": "OPEN"})
    for tid, state in task_states.items():
        fake_gh.responses[("issue", "view", tid, "--json", "state")] = json.dumps({"state": state})


def test_gh_failure_raises_with_stderr(fake_gh: FakeGh) -> None:
    fake_gh.fail_on = ("issue",)
    with pytest.raises(RuntimeError, match="boom"):
        linked_issues.task_done("1")


def test_linked_tasks_parses_marker(fake_gh: FakeGh) -> None:
    setup_issue(fake_gh, {"10": "CLOSED", "11": "OPEN"})
    assert linked_issues.linked_tasks(3) == ["10", "11"]


def test_linked_tasks_empty_without_marker(fake_gh: FakeGh) -> None:
    fake_gh.responses[("issue", "view")] = comments_json("nothing")
    assert linked_issues.linked_tasks(3) == []


def test_retire_comments_labels_closes_not_planned(fake_gh: FakeGh) -> None:
    fake_gh.responses[("issue", "view", "6", "--json", "comments")] = comments_json("hi")
    fake_gh.responses[("issue", "view", "6", "--json", "state")] = json.dumps({"state": "OPEN"})
    assert linked_issues.retire(6, "see #10") is True
    assert "see #10" in fake_gh.wrote("issue", "comment")[0][-1]
    assert fake_gh.wrote("issue", "edit", "6", "--add-label", "superseded")
    assert fake_gh.wrote("issue", "close", "6", "--reason", "not planned")


def test_retire_rerun_is_idempotent(fake_gh: FakeGh) -> None:
    fake_gh.responses[("issue", "view", "6", "--json", "comments")] = comments_json(marker("retire", 6))
    fake_gh.responses[("issue", "view", "6", "--json", "state")] = json.dumps({"state": "CLOSED"})
    assert linked_issues.retire(6) is False
    assert fake_gh.wrote("issue", "comment") == []
    assert fake_gh.wrote("issue", "close") == []


def test_sync_retires_when_all_tasks_closed(fake_gh: FakeGh) -> None:
    setup_issue(fake_gh, {"10": "CLOSED", "11": "CLOSED"})
    assert linked_issues.sync() == [3]
    assert fake_gh.wrote("issue", "close", "3")


def test_sync_leaves_issue_when_a_task_open(fake_gh: FakeGh) -> None:
    setup_issue(fake_gh, {"10": "CLOSED", "11": "OPEN"})
    assert linked_issues.sync() == []
    assert fake_gh.wrote("issue", "close") == []


def test_sync_dry_run_makes_no_mutating_call(fake_gh: FakeGh) -> None:
    setup_issue(fake_gh, {"10": "CLOSED"})
    assert linked_issues.sync(dry_run=True) == [3]
    for verb in ("comment", "edit", "close"):
        assert fake_gh.wrote("issue", verb) == []


def test_sync_ignores_issue_without_link_marker(fake_gh: FakeGh) -> None:
    fake_gh.responses[("issue", "list")] = json.dumps([{"number": 3}])
    fake_gh.responses[("issue", "view")] = comments_json("nothing")
    assert linked_issues.sync() == []

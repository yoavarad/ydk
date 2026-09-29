"""CLI tests for `ydk task sync-issues`. gh is faked at the subprocess boundary."""

from __future__ import annotations

import json
import subprocess

import pytest
from typer.testing import CliRunner

from ydk.cli import app
from ydk.core.linked_issues import MARKER_PREFIX

runner = CliRunner()


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    log: list[tuple[str, ...]] = []
    link = f"{MARKER_PREFIX}:link issue=3 tasks=10 -->"
    responses = {
        ("issue", "list"): json.dumps([{"number": 3}]),
        ("issue", "view", "3", "--json", "comments"): json.dumps({"comments": [{"body": link}]}),
        ("issue", "view", "3", "--json", "state"): json.dumps({"state": "OPEN"}),
        ("issue", "view", "10", "--json", "state"): json.dumps({"state": "CLOSED"}),
    }

    def fake(argv: list[str], **_kw: object) -> subprocess.CompletedProcess:
        args = tuple(argv[1:])
        log.append(args)
        for prefix, out in responses.items():
            if args[: len(prefix)] == prefix:
                return subprocess.CompletedProcess(argv, 0, out, "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake)
    return log


def test_sync_issues_retires_and_prints(calls: list[tuple[str, ...]]) -> None:
    result = runner.invoke(app, ["task", "sync-issues"])
    assert result.exit_code == 0
    assert "retired: #3" in result.output
    assert ("issue", "close", "3", "--reason", "not planned") in calls


def test_sync_issues_dry_run_no_mutation(calls: list[tuple[str, ...]]) -> None:
    result = runner.invoke(app, ["task", "sync-issues", "--dry-run"])
    assert result.exit_code == 0
    assert "retired: #3" in result.output
    assert not [c for c in calls if c[:2] in (("issue", "comment"), ("issue", "edit"), ("issue", "close"))]


def test_sync_issues_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda argv, **_kw: subprocess.CompletedProcess(argv, 0, "[]", ""))
    result = runner.invoke(app, ["task", "sync-issues"])
    assert result.exit_code == 0
    assert "retired: none" in result.output


def test_sync_issues_malformed_gh_output_clean_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda argv, **_kw: subprocess.CompletedProcess(argv, 0, "not json", ""))
    result = runner.invoke(app, ["task", "sync-issues"])
    assert result.exit_code != 0
    assert not isinstance(result.exception, json.JSONDecodeError)
    assert "invalid JSON" in result.output


def test_sync_issues_json(calls: list[tuple[str, ...]]) -> None:
    result = runner.invoke(app, ["--format", "json", "task", "sync-issues", "--dry-run"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {"retired": [3]}

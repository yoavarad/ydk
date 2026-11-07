"""CLI tests for `ydk task sync-issues`. gh is faked at the subprocess boundary."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from ydk.cli import app
from ydk.core.linked_issues import MARKER_PREFIX

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _write_remote(root: Path, remote: str) -> None:
    (root / ".ydk").mkdir(exist_ok=True)
    (root / ".ydk" / "config.yaml").write_text(f"project:\n  name: x\n  remote: {remote}\n", encoding="utf-8")


@pytest.fixture(autouse=True)
def _github_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_remote(tmp_path, "github")
    monkeypatch.chdir(tmp_path)


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
    assert "would retire: #3" in result.output
    assert "retired:" not in result.output.replace("would retire:", "")
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
    assert json.loads(result.output) == {"would_retire": [3], "dry_run": True}


def test_sync_issues_dry_run_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda argv, **_kw: subprocess.CompletedProcess(argv, 0, "[]", ""))
    result = runner.invoke(app, ["task", "sync-issues", "--dry-run"])
    assert result.exit_code == 0
    assert "would retire: none" in result.output


def test_sync_issues_json_real_run(calls: list[tuple[str, ...]]) -> None:
    result = runner.invoke(app, ["--format", "json", "task", "sync-issues"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {"retired": [3], "dry_run": False}


def test_sync_issues_gitlab_remote_is_github_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_remote(tmp_path, "gitlab")
    ran: list[list[str]] = []

    def fake(argv: list[str], **_kw: object) -> subprocess.CompletedProcess:
        ran.append(argv)
        return subprocess.CompletedProcess(argv, 0, "[]", "")

    monkeypatch.setattr(subprocess, "run", fake)
    result = runner.invoke(app, ["task", "sync-issues"])
    assert result.exit_code == 1
    assert "GitHub-only" in result.output
    assert ran == []


def test_sync_issues_github_remote_invokes_gh(calls: list[tuple[str, ...]]) -> None:
    result = runner.invoke(app, ["task", "sync-issues"])
    assert result.exit_code == 0
    assert calls
    assert calls[0][:2] == ("issue", "list")

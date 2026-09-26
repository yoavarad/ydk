"""CLI against the GitHub backend: `task list --epic` and `task coverage` read story linkage from issue bodies."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import patch

import yaml
from typer.testing import CliRunner

from ydk.cli import app
from ydk.core.config import DEFAULT_CONFIG

if TYPE_CHECKING:
    from pathlib import Path

    from typer.testing import Result

runner = CliRunner()


def _issue(number: int, title: str, body: str, label: str) -> dict:
    return {
        "number": number,
        "title": title,
        "state": "OPEN",
        "labels": [{"name": label}],
        "body": body,
        "url": f"https://github.com/o/r/issues/{number}",
    }


STORIES = [
    _issue(10, "Story in epic 5", "**Epic**: #5\n**Spec refs**: docs/specs/orders.md", "story"),
    _issue(11, "Story in epic 6", "**Epic**: #6", "story"),
]
TASKS = [
    _issue(20, "Task under story 10", "**Story**: #10", "task"),
    _issue(21, "Task under story 11", "**Story**: #11", "task"),
    _issue(22, "Orphan task", "", "task"),
]


def _fake_gh(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Fake gh CLI boundary serving the STORIES / TASKS fixtures."""
    if cmd[:3] == ["gh", "issue", "list"]:
        label = cmd[cmd.index("--label") + 1]
        items = {"story": STORIES, "task": TASKS}.get(label, [])
        return subprocess.CompletedProcess(cmd, 0, json.dumps(items), "")
    if cmd[:3] == ["gh", "issue", "view"]:
        item = next(i for i in STORIES + TASKS if i["number"] == int(cmd[3]))
        return subprocess.CompletedProcess(cmd, 0, json.dumps(item), "")
    raise AssertionError(f"unexpected gh call: {cmd}")


def _setup_github_project(tmp_path: Path) -> None:
    config = {**DEFAULT_CONFIG, "project": {**DEFAULT_CONFIG["project"], "remote": "github"}}
    config_dir = tmp_path / ".ydk"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(yaml.dump(config, default_flow_style=False))


def _invoke(args: list[str]) -> Result:
    with (
        patch("ydk.repositories.github.tasks.run_gh", side_effect=_fake_gh),
        patch("ydk.repositories.github.stories.run_gh", side_effect=_fake_gh),
    ):
        return runner.invoke(app, args)


def test_task_list_epic_shows_tasks_under_epic_stories(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_github_project(tmp_path)
    result = _invoke(["--format", "json", "task", "list", "--epic", "5"])
    assert result.exit_code == 0, result.output
    ids = [t["id"] for t in json.loads(result.output)]
    assert ids == ["20"]


def test_task_coverage_reads_github_story_spec_refs(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    _setup_github_project(tmp_path)
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "orders.md").write_text("# Orders")
    (spec_dir / "billing.md").write_text("# Billing")
    result = _invoke(["--format", "json", "task", "coverage"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["covered"] == 1
    assert [u.replace("\\", "/") for u in data["uncovered"]] == ["docs/specs/billing.md"]

"""CLI tests for ``ydk task migrate --to github`` (gh CLI faked at the ``run_gh`` boundary)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from typer.testing import CliRunner

from tests.core.test_migrate import FakeGh
from ydk.cli import app
from ydk.models.pm import TaskCreate
from ydk.repositories.local.tasks import LocalTaskRepository

if TYPE_CHECKING:
    from pathlib import Path

    from typer.testing import Result

runner = CliRunner()


def _invoke(fake: FakeGh, args: list[str]) -> Result:
    with (
        patch("ydk.repositories.github.tasks.run_gh", side_effect=fake),
        patch("ydk.repositories.github.stories.run_gh", side_effect=fake),
        patch("ydk.repositories.github.epics.run_gh", side_effect=fake),
        patch("ydk.repositories.github._helpers.run_gh", side_effect=fake),
    ):
        return runner.invoke(app, args)


def test_migrate_dry_run_prints_plan_and_creates_nothing(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    task = LocalTaskRepository(tmp_path / ".ydk").create_task(TaskCreate(title="Ship it"))
    fake = FakeGh()
    result = _invoke(fake, ["task", "migrate", "--to", "github", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert task.id in result.output
    assert "create" in result.output
    assert fake.calls == []
    assert not (tmp_path / ".ydk" / "batch-mapping.json").exists()


def test_migrate_creates_issues_and_writes_mapping(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    task = LocalTaskRepository(tmp_path / ".ydk").create_task(TaskCreate(title="Ship it"))
    fake = FakeGh()
    result = _invoke(fake, ["--format", "json", "task", "migrate", "--to", "github"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert rows == [{"type": "task", "local_id": task.id, "title": "Ship it", "action": "create", "id": "#100"}]
    mapping = json.loads((tmp_path / ".ydk" / "batch-mapping.json").read_text(encoding="utf-8"))
    assert mapping == {task.id: "#100"}


def test_migrate_rejects_unsupported_target(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = _invoke(FakeGh(), ["task", "migrate", "--to", "gitlab"])
    assert result.exit_code != 0
    assert "github" in result.output

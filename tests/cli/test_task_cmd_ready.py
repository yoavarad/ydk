"""Tests for odk task ready CLI command."""

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from odk.cli import app
from odk.models.pm import TaskSummary

runner = CliRunner()


def _fake_ready() -> list[TaskSummary]:
    return [
        TaskSummary(id="T-aaa111", title="First ready", status="open", dependencies_met=True, dependents_count=3),
        TaskSummary(id="T-bbb222", title="Second ready", status="open", dependencies_met=True, dependents_count=1),
    ]


class TestTaskReadyCli:
    def test_human_output_shows_table(self) -> None:
        with patch("odk.cli.task_cmd._get_repo") as mock_repo:
            mock_repo.return_value.list_ready.return_value = _fake_ready()
            result = runner.invoke(app, ["task", "ready"])
        assert result.exit_code == 0
        assert "T-aaa111" in result.output
        assert "First ready" in result.output
        assert "T-bbb222" in result.output

    def test_json_output(self) -> None:
        with patch("odk.cli.task_cmd._get_repo") as mock_repo:
            mock_repo.return_value.list_ready.return_value = _fake_ready()
            result = runner.invoke(app, ["--format", "json", "task", "ready"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 2
        assert data[0]["id"] == "T-aaa111"
        assert data[0]["dependents_count"] == 3

    def test_empty_list(self) -> None:
        with patch("odk.cli.task_cmd._get_repo") as mock_repo:
            mock_repo.return_value.list_ready.return_value = []
            result = runner.invoke(app, ["task", "ready"])
        assert result.exit_code == 0
        assert "No ready tasks" in result.output

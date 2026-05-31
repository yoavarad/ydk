"""Tests for odk.output — formatters, console singleton, and live display."""

import json
import time

import pytest
import yaml
from pydantic import BaseModel
from rich.table import Table

from odk.models.evaluation import CriterionResult
from odk.output.console import console, err_console
from odk.output.formatters import (
    HumanFormatter,
    JsonFormatter,
    OutputFormat,
    YamlFormatter,
    get_formatter,
)
from odk.output.live import AgentStatus, LiveAgentDisplay


# ---------------------------------------------------------------------------
# Helper Pydantic model for formatter tests
# ---------------------------------------------------------------------------
class _SampleModel(BaseModel):
    name: str
    score: float


# ---------------------------------------------------------------------------
# Console singleton
# ---------------------------------------------------------------------------


class TestConsoleSingleton:
    def test_console_is_importable(self) -> None:
        assert console is not None

    def test_err_console_writes_to_stderr(self) -> None:
        assert err_console.stderr is True


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


class TestHumanFormatter:
    def test_formats_dict_to_string_containing_keys(self) -> None:
        fmt = HumanFormatter()
        result = fmt.format({"name": "alice", "score": 9.5})
        assert "name" in result
        assert "alice" in result

    def test_formats_string_as_is(self) -> None:
        fmt = HumanFormatter()
        assert fmt.format("hello world") == "hello world"


class TestJsonFormatter:
    def test_produces_valid_json(self) -> None:
        fmt = JsonFormatter()
        data = {"key": "value", "num": 42}
        result = fmt.format(data)
        parsed = json.loads(result)
        assert parsed == data

    def test_handles_pydantic_model(self) -> None:
        fmt = JsonFormatter()
        model = _SampleModel(name="test", score=8.0)
        result = fmt.format(model)
        parsed = json.loads(result)
        assert parsed == {"name": "test", "score": 8.0}


class TestYamlFormatter:
    def test_produces_valid_yaml(self) -> None:
        fmt = YamlFormatter()
        data = {"key": "value", "num": 42}
        result = fmt.format(data)
        parsed = yaml.safe_load(result)
        assert parsed == data

    def test_handles_pydantic_model(self) -> None:
        fmt = YamlFormatter()
        model = _SampleModel(name="test", score=8.0)
        result = fmt.format(model)
        parsed = yaml.safe_load(result)
        assert parsed == {"name": "test", "score": 8.0}


class TestGetFormatter:
    def test_returns_human_formatter(self) -> None:
        assert isinstance(get_formatter(OutputFormat.human), HumanFormatter)

    def test_returns_json_formatter(self) -> None:
        assert isinstance(get_formatter(OutputFormat.json), JsonFormatter)

    def test_returns_yaml_formatter(self) -> None:
        assert isinstance(get_formatter(OutputFormat.yaml), YamlFormatter)

    def test_raises_for_unknown_format(self) -> None:
        with pytest.raises(ValueError, match="Unknown"):
            get_formatter("xml")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# LiveAgentDisplay
# ---------------------------------------------------------------------------


class TestAgentStatus:
    def test_elapsed_pending(self) -> None:
        s = AgentStatus(agent_id="a1", agent_name="Agent1", group="g1")
        assert s.elapsed == "—"

    def test_elapsed_running(self) -> None:
        s = AgentStatus(
            agent_id="a1",
            agent_name="Agent1",
            group="g1",
            status="RUNNING",
            start_time=time.time() - 2.5,
        )
        # Should be roughly 2.5s
        elapsed = float(s.elapsed.rstrip("s"))
        assert 2.0 <= elapsed <= 4.0

    def test_elapsed_done(self) -> None:
        s = AgentStatus(
            agent_id="a1",
            agent_name="Agent1",
            group="g1",
            status="DONE",
            start_time=100.0,
            end_time=103.5,
        )
        assert s.elapsed == "3.5s"


class TestLiveAgentDisplay:
    def _make_display(self) -> LiveAgentDisplay:
        agents = [
            ("a1", "Completeness", "core", 8),
            ("a2", "Clarity", "core", 7),
            ("a3", "Testability", "extra", 6),
        ]
        return LiveAgentDisplay(agents)

    def test_constructor_creates_statuses(self) -> None:
        display = self._make_display()
        assert len(display.statuses) == 3
        assert display.statuses["a1"].agent_name == "Completeness"
        assert display.statuses["a1"].threshold == 8

    def test_update_changes_status(self) -> None:
        display = self._make_display()
        display.update("a1", "RUNNING")
        assert display.statuses["a1"].status == "RUNNING"

    def test_update_running_sets_start_time(self) -> None:
        display = self._make_display()
        display.update("a1", "RUNNING")
        assert display.statuses["a1"].start_time is not None

    def test_update_done_sets_end_time_and_score(self) -> None:
        display = self._make_display()
        display.update("a1", "RUNNING")
        display.update("a1", "DONE", score=9.0)
        assert display.statuses["a1"].end_time is not None
        assert display.statuses["a1"].score == 9.0

    def test_build_table_returns_rich_table(self) -> None:
        display = self._make_display()
        table = display.build_table()
        assert isinstance(table, Table)

    def test_build_table_shows_progress_count(self) -> None:
        display = self._make_display()
        display.update("a1", "DONE", score=9.0)
        table = display.build_table(title="Eval")
        # Title should contain progress like "1/3"
        assert table.title is not None
        assert "1/3" in table.title

    def test_summary_all_passed(self) -> None:
        display = self._make_display()
        results = [
            CriterionResult(criterion_id="a1", score=9.0, passed=True, reasoning="Good"),
            CriterionResult(criterion_id="a2", score=8.0, passed=True, reasoning="Good"),
            CriterionResult(criterion_id="a3", score=7.0, passed=True, reasoning="Good"),
        ]
        assert display.summary(results) is True

    def test_summary_some_failed(self) -> None:
        display = self._make_display()
        results = [
            CriterionResult(criterion_id="a1", score=9.0, passed=True, reasoning="Good"),
            CriterionResult(criterion_id="a2", score=3.0, passed=False, reasoning="Bad"),
        ]
        assert display.summary(results) is False

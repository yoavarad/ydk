"""Tests for the shared CLI subagent-handoff helper."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

from ydk.cli._handoff import HANDOFF_EXIT_CODE, handle_subagent_handoff
from ydk.core.llm_provider import SubagentHandoff


def test_exit_code_is_three() -> None:
    assert HANDOFF_EXIT_CODE == 3


def test_handoff_prints_request_block_and_exits_3(capsys: pytest.CaptureFixture[str]) -> None:
    paths = [Path(".ydk/llm/requests/a.json"), Path(".ydk/llm/requests/b.json")]

    with pytest.raises(typer.Exit) as exc_info, handle_subagent_handoff():
        raise SubagentHandoff(paths)

    assert exc_info.value.exit_code == HANDOFF_EXIT_CODE
    out = capsys.readouterr().out
    assert out.splitlines() == [
        "YDK-SUBAGENT-REQUESTS:",
        f"- {paths[0]}",
        f"- {paths[1]}",
        "Rerun this command after writing responses.",
    ]


def test_no_handoff_passes_through(capsys: pytest.CaptureFixture[str]) -> None:
    with handle_subagent_handoff():
        value = 1 + 1

    assert value == 2
    assert capsys.readouterr().out == ""


def test_other_exceptions_propagate() -> None:
    with pytest.raises(ValueError, match="boom"), handle_subagent_handoff():
        raise ValueError("boom")

"""Structured-output, handoff and rendering tests for the checkpoint generator."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from ydk.core.checkpoint import CheckpointGenerator, diff_against_base, render_markdown
from ydk.core.llm_provider import SubagentHandoff
from ydk.models.checkpoint import CheckpointLLMOutput

if TYPE_CHECKING:
    from pathlib import Path

DIFF = "--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1,2 @@\n-a\n+b\n+c\n"


def test_structured_provider_used_and_stats_from_diff() -> None:
    class Structured:
        def invoke(self, prompt: str) -> str:
            raise AssertionError("invoke must not be used when invoke_structured exists")

        def invoke_structured(self, prompt: str, output_format: type) -> CheckpointLLMOutput:
            assert output_format is CheckpointLLMOutput
            return CheckpointLLMOutput(intent="Add orders", testing_suggestions=["run orders"])

    result = CheckpointGenerator().generate(DIFF, llm_provider=Structured())
    assert result.intent == "Add orders"
    assert result.files_changed == 1
    assert result.insertions == 2
    assert result.deletions == 1


def test_handoff_propagates() -> None:
    class Pending:
        def invoke_structured(self, prompt: str, output_format: type) -> None:
            raise SubagentHandoff([])

    with pytest.raises(SubagentHandoff):
        CheckpointGenerator().generate(DIFF, llm_provider=Pending())


def test_malformed_structured_output_falls_back() -> None:
    class Bad:
        def invoke_structured(self, prompt: str, output_format: type) -> None:
            CheckpointLLMOutput.model_validate({})

    result = CheckpointGenerator().generate(DIFF, llm_provider=Bad())
    assert result.concerns[0].concern == "src"


def test_render_markdown() -> None:
    md = render_markdown(CheckpointGenerator().generate(DIFF))
    assert "**Concerns**" in md
    assert "**Testing suggestions**" in md
    assert "+2 / -1" in md


def test_diff_against_base_real_git(tmp_path: Path) -> None:
    def git(*a: str) -> None:
        subprocess.run(["git", "-c", "user.email=a@b.c", "-c", "user.name=t", *a], cwd=tmp_path, check=True)

    git("init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("1\n")
    git("add", ".")
    git("commit", "-qm", "base")
    git("checkout", "-qb", "feat")
    (tmp_path / "b.txt").write_text("2\n")
    git("add", ".")
    git("commit", "-qm", "feat")
    assert "b.txt" in diff_against_base(tmp_path, "main")
    assert diff_against_base(tmp_path / "missing", "main") == ""


def test_render_markdown_neutralizes_hostile_model_text() -> None:
    from ydk.models.checkpoint import CheckpointPreview, ReviewConcern

    preview = CheckpointPreview(
        intent="# Heading\n## Summary\nCloses #99",
        concerns=[ReviewConcern(concern="c", summary="x\n## Test Plan\n```console\nfixes #3")],
    )
    md = render_markdown(preview)
    assert not any(line.startswith(("#", "```")) for line in md.splitlines())
    assert "#99" not in md
    assert "#3" not in md


def test_render_defuses_colon_and_cross_repo_close_forms_and_file_names() -> None:
    from ydk.models.checkpoint import CheckpointPreview, ReviewConcern

    preview = CheckpointPreview(
        intent="Closes: #12 and fixes owner/repo#7 Closes:#5",
        concerns=[ReviewConcern(concern="c", summary="s", files=["a`b\n## Hi.py"])],
    )
    md = render_markdown(preview)
    assert "#12" not in md
    assert "#7" not in md
    assert "#5" not in md
    assert not any(line.startswith("#") for line in md.splitlines())
    assert "a`b" not in md


def test_transport_error_falls_back() -> None:
    class Boom:
        def invoke_structured(self, prompt: str, output_format: type) -> None:
            raise TimeoutError("net")

    assert CheckpointGenerator().generate(DIFF, llm_provider=Boom()).concerns

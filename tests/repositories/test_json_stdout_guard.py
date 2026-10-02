"""Tests for UTF-8 decode of gh/glab output and the empty-JSON-stdout guard."""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch

import pytest

from ydk.repositories.github import _helpers as gh_helpers
from ydk.repositories.github.epics import GitHubEpicRepository
from ydk.repositories.github.stories import GitHubStoryRepository
from ydk.repositories.github.tasks import GitHubTaskRepository
from ydk.repositories.gitlab import _helpers as gl_helpers
from ydk.repositories.gitlab.epics import GitLabEpicRepository
from ydk.repositories.gitlab.stories import GitLabStoryRepository
from ydk.repositories.gitlab.tasks import GitLabTaskRepository

_EMIT = "import sys; sys.stdout.buffer.write('\u201dok'.encode('utf-8'))"


def _done(stdout: str | None, stderr: str = "boom") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)  # type: ignore[arg-type]


@pytest.mark.parametrize("run", [gh_helpers.run_gh, gl_helpers.run_glab])
def test_run_decodes_utf8_under_cp1252(run, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    result = run([sys.executable, "-c", _EMIT])
    assert result.stdout == "”ok"


@pytest.mark.parametrize("mod", [gh_helpers, gl_helpers])
@pytest.mark.parametrize("stdout", [None, "", "  \n"])
def test_load_json_stdout_raises_runtime_error_with_stderr(mod, stdout: str | None) -> None:
    with pytest.raises(RuntimeError, match=r"issue view.*boom"):
        mod.load_json_stdout(_done(stdout), "issue view")


@pytest.mark.parametrize("mod", [gh_helpers, gl_helpers])
def test_load_json_stdout_parses(mod) -> None:
    assert mod.load_json_stdout(_done('{"a": 1}'), "x") == {"a": 1}


@pytest.mark.parametrize(
    ("target", "call"),
    [
        ("ydk.repositories.github.tasks.run_gh", lambda: GitHubTaskRepository().get(1)),
        ("ydk.repositories.github.tasks.run_gh", lambda: GitHubTaskRepository().list()),
        ("ydk.repositories.github.epics.run_gh", lambda: GitHubEpicRepository().get(1)),
        ("ydk.repositories.github.stories.run_gh", lambda: GitHubStoryRepository().get(1)),
        ("ydk.repositories.gitlab.tasks.run_glab", lambda: GitLabTaskRepository().get(1)),
        ("ydk.repositories.gitlab.epics.run_glab", lambda: GitLabEpicRepository().get(1)),
        ("ydk.repositories.gitlab.stories.run_glab", lambda: GitLabStoryRepository().get(1)),
    ],
)
def test_empty_stdout_raises_runtime_error_not_type_error(target: str, call) -> None:
    with patch(target, return_value=_done(None)), pytest.raises(RuntimeError, match="boom"):
        call()

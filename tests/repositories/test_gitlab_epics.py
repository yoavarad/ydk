"""Tests for GitLabEpicRepository -- all glab CLI calls are mocked."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ydk.repositories.gitlab.epics import GitLabEpicRepository


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestMarkRetroDone:
    @pytest.mark.parametrize("epic_ref", ["9", "#9", "E-009"])
    @patch("ydk.repositories.gitlab.epics.run_glab")
    def test_labels_and_notes_the_epic_issue(self, mock_run: MagicMock, epic_ref: str) -> None:
        mock_run.return_value = _completed()
        repo = GitLabEpicRepository()

        repo.mark_retro_done(epic_ref, ".ydk/retros/E-009.md")

        calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["glab", "issue", "update", "9", "--label", "retro-done"] in calls
        assert ["glab", "issue", "note", "9", "--message", "Retrospective recorded: .ydk/retros/E-009.md"] in calls

    @patch("ydk.repositories.gitlab.epics.run_glab")
    def test_raises_when_glab_fails(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="boom")
        repo = GitLabEpicRepository()

        with pytest.raises(RuntimeError, match="boom"):
            repo.mark_retro_done("9", ".ydk/retros/E-009.md")

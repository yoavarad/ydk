"""Tests for GitLabStoryRepository -- all glab CLI calls are mocked."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ydk.repositories.gitlab.stories import GitLabStoryRepository


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _story(iid: int, epic: str | None) -> dict:
    body = (f"**Epic**: {epic}\n\n" if epic else "") + "### Description\nx\n"
    return {"iid": iid, "title": f"Story {iid}", "state": "opened", "description": body, "labels": ["kind:story"]}


class TestListStories:
    @patch("ydk.repositories.gitlab.stories.run_glab")
    def test_lists_all_story_labelled_issues(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(stdout=json.dumps([_story(2, "#1"), _story(3, None)]))

        stories = GitLabStoryRepository().list_stories()

        assert [s.number for s in stories] == [2, 3]
        cmd = mock_run.call_args[0][0]
        assert cmd[cmd.index("--label") + 1] == "kind:story"

    @pytest.mark.parametrize("epic_ref", ["1", "#1", "E-001"])
    @patch("ydk.repositories.gitlab.stories.run_glab")
    def test_filters_by_epic(self, mock_run: MagicMock, epic_ref: str) -> None:
        mock_run.return_value = _completed(
            stdout=json.dumps([_story(2, "#1"), _story(3, "#4"), _story(5, None), _story(6, "E-001")])
        )

        stories = GitLabStoryRepository().list_stories(epic_id=epic_ref)

        assert [s.number for s in stories] == [2, 6]

    @patch("ydk.repositories.gitlab.stories.run_glab")
    def test_unparseable_epic_ref_matches_verbatim(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(stdout=json.dumps([_story(2, "my-epic"), _story(3, "#1")]))

        assert [s.number for s in GitLabStoryRepository().list_stories(epic_id="my-epic")] == [2]

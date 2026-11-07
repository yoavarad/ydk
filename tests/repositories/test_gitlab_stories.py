"""Tests for GitLabStoryRepository -- all glab CLI calls are mocked."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ydk.models.pm import StoryCreate
from ydk.repositories.gitlab.stories import GitLabStoryRepository


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _story(iid: int, epic: str | None) -> dict:
    body = (f"**Epic**: {epic}\n\n" if epic else "") + "### Description\nx\n"
    return {"iid": iid, "title": f"Story {iid}", "state": "opened", "description": body, "labels": ["kind:story"]}


class TestCreateStory:
    @patch("ydk.repositories.gitlab.stories.run_glab")
    def test_creates_story_labelled_issue(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(stdout="https://gitlab.com/owner/repo/-/issues/4")

        detail = GitLabStoryRepository().create_story(StoryCreate(title="S", epic_id="3", description="d"))

        assert (detail.number, detail.epic_id, detail.labels) == (4, "3", ["kind:story"])
        call_args = mock_run.call_args[0][0]
        assert call_args[0:3] == ["glab", "issue", "create"]
        assert call_args[call_args.index("--label") + 1] == "kind:story"
        assert "**Epic**: 3" in call_args[call_args.index("--description") + 1]


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

"""Tests for LocalStoryRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ydk.models.pm import StoryCreate
from ydk.repositories.local.stories import LocalStoryRepository

if TYPE_CHECKING:
    from pathlib import Path


class TestListStories:
    def test_story_without_epic_lists_with_empty_epic_id(self, tmp_path: Path) -> None:
        repo = LocalStoryRepository(tmp_path)
        sid = repo.create_story(StoryCreate(title="Lone")).id

        assert [(s.id, s.epic_id) for s in repo.list_stories()] == [(sid, "")]

    def test_filters_by_epic(self, tmp_path: Path) -> None:
        repo = LocalStoryRepository(tmp_path)
        inside = repo.create_story(StoryCreate(title="In", epic_id="E-001")).id
        repo.create_story(StoryCreate(title="Out", epic_id="E-002"))

        assert [s.id for s in repo.list_stories(epic_id="E-001")] == [inside]

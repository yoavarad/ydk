"""Tests for LocalEpicRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ydk.models.pm import EpicCreate
from ydk.repositories.local.epics import LocalEpicRepository

if TYPE_CHECKING:
    from pathlib import Path


class TestListEpics:
    def test_filters_by_status_by_default_open(self, tmp_path: Path) -> None:
        repo = LocalEpicRepository(tmp_path)
        first = repo.create_epic(EpicCreate(title="First")).id
        second = repo.create_epic(EpicCreate(title="Second")).id
        repo.update_status(second, "done")

        assert [(e.id, e.title, e.status) for e in repo.list_epics()] == [(first, "First", "open")]
        assert [e.id for e in repo.list_epics(status="done")] == [second]

    def test_all_returns_every_epic(self, tmp_path: Path) -> None:
        repo = LocalEpicRepository(tmp_path)
        first = repo.create_epic(EpicCreate(title="First")).id
        second = repo.create_epic(EpicCreate(title="Second")).id
        repo.update_status(second, "done")

        assert {e.id: e.status for e in repo.list_epics(status="all")} == {first: "open", second: "done"}

    def test_empty_when_no_epics(self, tmp_path: Path) -> None:
        assert LocalEpicRepository(tmp_path).list_epics(status="all") == []

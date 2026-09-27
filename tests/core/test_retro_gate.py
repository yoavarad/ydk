"""Tests for ydk.core.retro_gate — finding finished epics without a retrospective."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ydk.core.retro_gate import find_epics_missing_retro
from ydk.repositories.local.epics import LocalEpicRepository

if TYPE_CHECKING:
    from pathlib import Path


def _make_repo(tmp_path: Path) -> LocalEpicRepository:
    from ydk.models.pm import EpicCreate

    repo = LocalEpicRepository(tmp_path / ".ydk")
    detail = repo.create_epic(EpicCreate(title="Epic One"))
    return repo, detail.id  # type: ignore[return-value]


class TestFindEpicsMissingRetro:
    def test_no_finished_epics_returns_empty(self, tmp_path: Path) -> None:
        repo, _epic_id = _make_repo(tmp_path)
        # Epic stays "open" -- never finished.
        missing = find_epics_missing_retro(repo, retros_dir=tmp_path / ".ydk" / "retros")
        assert missing == []

    def test_finished_epic_with_retro_recorded_returns_empty(self, tmp_path: Path) -> None:
        repo, epic_id = _make_repo(tmp_path)
        repo.update_status(epic_id, "done")
        retros_dir = tmp_path / ".ydk" / "retros"
        retros_dir.mkdir(parents=True)
        (retros_dir / f"{epic_id}.md").write_text("# Retro", encoding="utf-8")
        repo.mark_retro_done(epic_id, str(retros_dir / f"{epic_id}.md"))

        missing = find_epics_missing_retro(repo, retros_dir=retros_dir)
        assert missing == []

    def test_finished_epic_without_retro_is_reported(self, tmp_path: Path) -> None:
        repo, epic_id = _make_repo(tmp_path)
        repo.update_status(epic_id, "done")

        missing = find_epics_missing_retro(repo, retros_dir=tmp_path / ".ydk" / "retros")
        assert len(missing) == 1
        assert missing[0].epic_id == epic_id
        assert missing[0].title == "Epic One"

    def test_closed_status_also_counts_as_finished(self, tmp_path: Path) -> None:
        repo, epic_id = _make_repo(tmp_path)
        repo.update_status(epic_id, "closed")

        missing = find_epics_missing_retro(repo, retros_dir=tmp_path / ".ydk" / "retros")
        assert len(missing) == 1
        assert missing[0].epic_id == epic_id

    def test_backend_with_only_list_method_is_supported(self, tmp_path: Path) -> None:
        """GitLab's epic repo has no `list_epics` alias -- only `.list(status=...)`."""

        class _ListOnlyRepo:
            def list(self, *, status: str) -> list:
                assert status == "all"
                return [type("Epic", (), {"id": "5", "number": 5, "title": "Finished", "status": "closed"})()]

        missing = find_epics_missing_retro(_ListOnlyRepo(), retros_dir=tmp_path / ".ydk" / "retros")  # type: ignore[arg-type]
        assert len(missing) == 1
        assert missing[0].epic_id == "5"

    def test_backend_with_neither_shape_returns_empty(self, tmp_path: Path) -> None:
        missing = find_epics_missing_retro(object(), retros_dir=tmp_path / ".ydk" / "retros")  # type: ignore[arg-type]
        assert missing == []

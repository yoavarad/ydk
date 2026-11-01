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


class _FakeEpic:
    def __init__(self, epic_id: str, title: str, url: str = "", status: str = "closed") -> None:
        self.id = epic_id
        self.number = epic_id
        self.title = title
        self.url = url
        self.status = status


class _FakeRepo:
    def __init__(self, *epics: _FakeEpic) -> None:
        self._epics = list(epics)

    def list(self, *, status: str) -> list:
        return self._epics


def _write_retro(path: Path, epic_id: str, title: str, url: str = "") -> None:
    from ydk.core.retro_gate import render_frontmatter

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_frontmatter(epic_id, title, url) + "# Retrospective\n", encoding="utf-8")


class TestRetroIdentity:
    def test_matching_frontmatter_covers_epic(self, tmp_path: Path) -> None:
        _write_retro(tmp_path / "11.md", "11", "Alpha  epic", "http://x/11")
        repo = _FakeRepo(_FakeEpic("11", "Alpha epic", "http://x/11"))
        assert find_epics_missing_retro(repo, retros_dir=tmp_path) == []  # type: ignore[arg-type]

    def test_mismatched_title_is_missing(self, tmp_path: Path) -> None:
        _write_retro(tmp_path / "11.md", "11", "Old epic")
        repo = _FakeRepo(_FakeEpic("11", "New epic"))
        assert [m.epic_id for m in find_epics_missing_retro(repo, retros_dir=tmp_path)] == ["11"]  # type: ignore[arg-type]

    def test_mismatched_url_is_missing(self, tmp_path: Path) -> None:
        _write_retro(tmp_path / "11.md", "11", "Same", "http://old/11")
        repo = _FakeRepo(_FakeEpic("11", "Same", "http://new/11"))
        assert len(find_epics_missing_retro(repo, retros_dir=tmp_path)) == 1  # type: ignore[arg-type]

    def test_empty_url_on_either_side_ignored(self, tmp_path: Path) -> None:
        _write_retro(tmp_path / "11.md", "11", "Same", "")
        repo = _FakeRepo(_FakeEpic("11", "Same", "http://new/11"))
        assert find_epics_missing_retro(repo, retros_dir=tmp_path) == []  # type: ignore[arg-type]

    def test_legacy_file_without_frontmatter_covers_epic(self, tmp_path: Path) -> None:
        (tmp_path / "11.md").write_text("# Retrospective: 11\n", encoding="utf-8")
        repo = _FakeRepo(_FakeEpic("11", "Anything"))
        assert find_epics_missing_retro(repo, retros_dir=tmp_path) == []  # type: ignore[arg-type]

    def test_suffixed_file_covers_epic(self, tmp_path: Path) -> None:
        _write_retro(tmp_path / "11.md", "11", "Old epic")
        _write_retro(tmp_path / "11-new-epic.md", "11", "New epic")
        repo = _FakeRepo(_FakeEpic("11", "New epic"))
        assert find_epics_missing_retro(repo, retros_dir=tmp_path) == []  # type: ignore[arg-type]


class TestResolveRetroPath:
    def test_plain_when_absent(self, tmp_path: Path) -> None:
        from ydk.core.retro_gate import resolve_retro_path

        assert resolve_retro_path(tmp_path, "11", "T", "") == tmp_path / "11.md"

    def test_plain_when_same_epic(self, tmp_path: Path) -> None:
        from ydk.core.retro_gate import resolve_retro_path

        _write_retro(tmp_path / "11.md", "11", "T")
        assert resolve_retro_path(tmp_path, "11", "T", "") == tmp_path / "11.md"

    def test_slug_when_other_epic(self, tmp_path: Path) -> None:
        from ydk.core.retro_gate import resolve_retro_path

        _write_retro(tmp_path / "11.md", "11", "Old")
        assert resolve_retro_path(tmp_path, "11", "New Epic: Go!", "") == tmp_path / "11-new-epic-go.md"

    def test_lookup_epic(self) -> None:
        from ydk.core.retro_gate import lookup_epic

        repo = _FakeRepo(_FakeEpic("11", "T", "u"))
        assert lookup_epic(repo, "11") == ("T", "u")  # type: ignore[arg-type]
        assert lookup_epic(repo, "12") is None  # type: ignore[arg-type]

    def test_third_epic_same_title_gets_numbered_file(self, tmp_path: Path) -> None:
        from ydk.core.retro_gate import resolve_retro_path

        _write_retro(tmp_path / "11.md", "11", "Old")
        _write_retro(tmp_path / "11-new.md", "11", "New", "http://a/11")
        assert resolve_retro_path(tmp_path, "11", "New", "http://b/11") == tmp_path / "11-new-2.md"
        assert resolve_retro_path(tmp_path, "11", "New", "http://a/11") == tmp_path / "11-new.md"

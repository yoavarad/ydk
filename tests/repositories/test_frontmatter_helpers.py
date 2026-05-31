"""Tests for shared frontmatter helpers (update_file_status, append_comment)."""

from pathlib import Path

from odk.repositories.local.frontmatter import (
    append_comment,
    parse_frontmatter,
    render_frontmatter,
    update_file_status,
)
from odk.repositories.local.manifest import Manifest


def _write_item(directory: Path, item_id: str, status: str = "open") -> Path:
    """Write a minimal markdown file with frontmatter. Returns file path."""
    directory.mkdir(parents=True, exist_ok=True)
    fm = {"id": item_id, "title": "Test item", "status": status, "updated": ""}
    body = "## Description\n\nTest.\n\n## Activity Log\n"
    path = directory / f"{item_id}.md"
    path.write_text(render_frontmatter(fm, body), encoding="utf-8")
    return path


def _seed_manifest(tmp_path: Path, key: str, item_id: str) -> Manifest:
    """Create a manifest with a single item entry."""
    manifest = Manifest(tmp_path)
    data = manifest.load()
    data[key][item_id] = {"title": "Test item", "status": "open"}
    manifest.save(data)
    return manifest


class TestUpdateFileStatus:
    def test_updates_frontmatter_status(self, tmp_path: Path) -> None:
        file_path = _write_item(tmp_path / "tasks", "T-001")
        manifest = _seed_manifest(tmp_path, "tasks", "T-001")

        update_file_status(file_path, "T-001", "in-progress", manifest, "tasks")

        fm, _body = parse_frontmatter(file_path.read_text(encoding="utf-8"))
        assert fm["status"] == "in-progress"
        assert fm["updated"] != ""

    def test_updates_manifest_status(self, tmp_path: Path) -> None:
        file_path = _write_item(tmp_path / "tasks", "T-001")
        manifest = _seed_manifest(tmp_path, "tasks", "T-001")

        update_file_status(file_path, "T-001", "done", manifest, "tasks")

        data = manifest.load()
        assert data["tasks"]["T-001"]["status"] == "done"

    def test_skips_manifest_if_item_not_present(self, tmp_path: Path) -> None:
        file_path = _write_item(tmp_path / "epics", "E-099")
        manifest = Manifest(tmp_path)

        # Should not raise even though E-099 is not in the manifest
        update_file_status(file_path, "E-099", "closed", manifest, "epics")

        fm, _body = parse_frontmatter(file_path.read_text(encoding="utf-8"))
        assert fm["status"] == "closed"

    def test_works_for_stories(self, tmp_path: Path) -> None:
        file_path = _write_item(tmp_path / "stories", "S-001")
        manifest = _seed_manifest(tmp_path, "stories", "S-001")

        update_file_status(file_path, "S-001", "in-review", manifest, "stories")

        fm, _body = parse_frontmatter(file_path.read_text(encoding="utf-8"))
        assert fm["status"] == "in-review"
        assert manifest.load()["stories"]["S-001"]["status"] == "in-review"


class TestAppendComment:
    def test_appends_comment_to_body(self, tmp_path: Path) -> None:
        file_path = _write_item(tmp_path / "tasks", "T-001")

        append_comment(file_path, "Progress update")

        content = file_path.read_text(encoding="utf-8")
        assert "Progress update" in content

    def test_updates_frontmatter_timestamp(self, tmp_path: Path) -> None:
        file_path = _write_item(tmp_path / "tasks", "T-001")

        append_comment(file_path, "Done")

        fm, _body = parse_frontmatter(file_path.read_text(encoding="utf-8"))
        assert fm["updated"] != ""
        assert "T" in fm["updated"]  # ISO format contains T

    def test_timestamp_suffix_is_included(self, tmp_path: Path) -> None:
        file_path = _write_item(tmp_path / "tasks", "T-001")

        append_comment(file_path, "Note", timestamp_suffix=" (UTC)")

        content = file_path.read_text(encoding="utf-8")
        assert "(UTC)" in content

    def test_multiple_comments_accumulate(self, tmp_path: Path) -> None:
        file_path = _write_item(tmp_path / "tasks", "T-001")

        append_comment(file_path, "First comment")
        append_comment(file_path, "Second comment")

        content = file_path.read_text(encoding="utf-8")
        assert "First comment" in content
        assert "Second comment" in content

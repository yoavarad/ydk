"""Tests for deterministic three-way merge of YDK bookkeeping files."""

from __future__ import annotations

import pytest
import yaml

from ydk.repositories.local.bookkeeping_merge import (
    merge_manifest,
    merge_task_file,
    merge_text,
)
from ydk.repositories.local.frontmatter import parse_frontmatter, render_frontmatter


def _manifest(tasks: dict, **extra: object) -> dict:
    data: dict = {
        "last_task_id": 0,
        "last_story_id": 0,
        "last_epic_id": 0,
        "epics": {},
        "stories": {},
        "tasks": tasks,
    }
    data.update(extra)
    return data


class TestMergeManifest:
    def test_add_add_keeps_both_tasks(self) -> None:
        base = _manifest({})
        ours = _manifest({"T-1": {"title": "one", "status": "open"}})
        theirs = _manifest({"T-2": {"title": "two", "status": "open"}})

        merged = merge_manifest(base, ours, theirs)

        assert merged["tasks"] == {
            "T-1": {"title": "one", "status": "open"},
            "T-2": {"title": "two", "status": "open"},
        }

    def test_add_on_one_side_status_change_on_other(self) -> None:
        base = _manifest({"T-1": {"title": "one", "status": "open"}})
        ours = _manifest(
            {
                "T-1": {"title": "one", "status": "open"},
                "T-2": {"title": "two", "status": "in-progress"},
            }
        )
        theirs = _manifest({"T-1": {"title": "one", "status": "done"}})

        merged = merge_manifest(base, ours, theirs)

        assert merged["tasks"]["T-1"]["status"] == "done"
        assert merged["tasks"]["T-2"]["status"] == "in-progress"

    def test_same_task_status_conflict_picks_most_advanced(self) -> None:
        base = _manifest({"T-1": {"title": "one", "status": "open"}})
        ours = _manifest({"T-1": {"title": "one", "status": "in-progress"}})
        theirs = _manifest({"T-1": {"title": "one", "status": "done"}})

        assert merge_manifest(base, ours, theirs)["tasks"]["T-1"]["status"] == "done"
        assert merge_manifest(base, theirs, ours)["tasks"]["T-1"]["status"] == "done"

    def test_counters_take_max(self) -> None:
        base = _manifest({}, last_task_id=1)
        ours = _manifest({}, last_task_id=3)
        theirs = _manifest({}, last_task_id=2)

        assert merge_manifest(base, ours, theirs)["last_task_id"] == 3

    def test_lists_are_unioned_in_order(self) -> None:
        base = _manifest({}, stories={"S-1": {"tasks": ["T-0"]}})
        ours = _manifest({}, stories={"S-1": {"tasks": ["T-0", "T-1"]}})
        theirs = _manifest({}, stories={"S-1": {"tasks": ["T-0", "T-2"]}})

        merged = merge_manifest(base, ours, theirs)

        assert merged["stories"]["S-1"]["tasks"] == ["T-0", "T-1", "T-2"]

    def test_deleted_on_one_side_unchanged_on_other_is_dropped(self) -> None:
        entry = {"title": "one", "status": "open"}
        base = _manifest({"T-1": entry})
        ours = _manifest({})
        theirs = _manifest({"T-1": dict(entry)})

        assert "T-1" not in merge_manifest(base, ours, theirs)["tasks"]

    def test_deleted_on_one_side_modified_on_other_is_kept(self) -> None:
        base = _manifest({"T-1": {"title": "one", "status": "open"}})
        ours = _manifest({})
        theirs = _manifest({"T-1": {"title": "one", "status": "done"}})

        assert merge_manifest(base, ours, theirs)["tasks"]["T-1"]["status"] == "done"

    def test_other_scalar_conflict_prefers_ours(self) -> None:
        base = _manifest({"T-1": {"title": "one"}})
        ours = _manifest({"T-1": {"title": "ours"}})
        theirs = _manifest({"T-1": {"title": "theirs"}})

        assert merge_manifest(base, ours, theirs)["tasks"]["T-1"]["title"] == "ours"


class TestMergeTaskFile:
    def test_frontmatter_status_and_activity_log_both_kept(self) -> None:
        base = render_frontmatter({"id": "T-1", "status": "open"}, "## Activity Log\n- created")
        ours = render_frontmatter(
            {"id": "T-1", "status": "in-progress"},
            "## Activity Log\n- created\n- started",
        )
        theirs = render_frontmatter(
            {"id": "T-1", "status": "done"},
            "## Activity Log\n- created\n- closed",
        )

        fm, body = parse_frontmatter(merge_task_file(base, ours, theirs))

        assert fm["status"] == "done"
        assert body.splitlines() == [
            "## Activity Log",
            "- created",
            "- started",
            "- closed",
        ]

    def test_file_without_base_add_add(self) -> None:
        ours = render_frontmatter({"id": "T-1", "status": "open"}, "ours body")
        theirs = render_frontmatter({"id": "T-1", "status": "done"}, "theirs body")

        fm, body = parse_frontmatter(merge_task_file("", ours, theirs))

        assert fm["status"] == "done"
        assert "ours body" in body
        assert "theirs body" in body


class TestMergeText:
    def test_dispatches_manifest_by_path(self) -> None:
        base = yaml.dump(_manifest({}))
        ours = yaml.dump(_manifest({"T-1": {"status": "open"}}))
        theirs = yaml.dump(_manifest({"T-2": {"status": "open"}}))

        merged = yaml.safe_load(merge_text(".ydk/manifest.yaml", base, ours, theirs))

        assert set(merged["tasks"]) == {"T-1", "T-2"}

    def test_non_mapping_manifest_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="not a mapping"):
            merge_text(".ydk/manifest.yaml", "", "- a\n- b\n", "")

    def test_dispatches_task_file_by_suffix(self) -> None:
        base = render_frontmatter({"status": "open"}, "b")
        ours = render_frontmatter({"status": "open"}, "b")
        theirs = render_frontmatter({"status": "done"}, "b")

        fm, _ = parse_frontmatter(merge_text(".ydk/tasks/T-1.md", base, ours, theirs))

        assert fm["status"] == "done"

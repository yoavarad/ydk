"""Tests for intelligent navigation — stage detection and recommendations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ydk.core.navigation import detect_stage, recommend_next_action, scan_project

if TYPE_CHECKING:
    from pathlib import Path
from ydk.models.navigation import NavigationStatus, ProjectStage


class TestDetectStage:
    def test_empty_when_no_ydk_dir(self, tmp_path: Path) -> None:
        assert detect_stage(tmp_path / ".ydk") == ProjectStage.EMPTY

    def test_initialized_when_ydk_dir_exists_but_empty(self, tmp_path: Path) -> None:
        ydk = tmp_path / ".ydk"
        ydk.mkdir()
        assert detect_stage(ydk) == ProjectStage.INITIALIZED

    def test_specified_when_specs_exist(self, tmp_path: Path) -> None:
        ydk = tmp_path / ".ydk"
        specs = ydk / "specs"
        specs.mkdir(parents=True)
        (specs / "api.md").write_text("# API Spec")
        assert detect_stage(ydk) == ProjectStage.SPECIFIED

    def test_tasked_when_tasks_exist_all_open(self, tmp_path: Path) -> None:
        ydk = tmp_path / ".ydk"
        tasks = ydk / "tasks"
        tasks.mkdir(parents=True)
        (tasks / "T-001.md").write_text("---\nstatus: open\n---\nTask 1")
        assert detect_stage(ydk) == ProjectStage.TASKED

    def test_in_progress_when_task_in_progress(self, tmp_path: Path) -> None:
        ydk = tmp_path / ".ydk"
        tasks = ydk / "tasks"
        tasks.mkdir(parents=True)
        (tasks / "T-001.md").write_text("---\nstatus: in-progress\n---\nTask 1")
        assert detect_stage(ydk) == ProjectStage.IN_PROGRESS

    def test_in_progress_when_task_done(self, tmp_path: Path) -> None:
        ydk = tmp_path / ".ydk"
        tasks = ydk / "tasks"
        tasks.mkdir(parents=True)
        (tasks / "T-001.md").write_text("---\nstatus: done\n---\nTask 1")
        assert detect_stage(ydk) == ProjectStage.IN_PROGRESS

    def test_reviewing_when_task_in_review(self, tmp_path: Path) -> None:
        ydk = tmp_path / ".ydk"
        tasks = ydk / "tasks"
        tasks.mkdir(parents=True)
        (tasks / "T-001.md").write_text("---\nstatus: in-review\n---\nTask 1")
        assert detect_stage(ydk) == ProjectStage.REVIEWING


class TestRecommendNextAction:
    def test_empty_recommends_init(self) -> None:
        action = recommend_next_action(ProjectStage.EMPTY, {})
        assert "ydk init" in action

    def test_initialized_recommends_spec(self) -> None:
        action = recommend_next_action(ProjectStage.INITIALIZED, {})
        assert "ydk spec create" in action

    def test_specified_recommends_task_create(self) -> None:
        action = recommend_next_action(ProjectStage.SPECIFIED, {})
        assert "ydk task create" in action

    def test_tasked_recommends_task_ready(self) -> None:
        action = recommend_next_action(ProjectStage.TASKED, {"open": 3})
        assert "ydk task ready" in action

    def test_in_progress_shows_blocked_warning(self) -> None:
        action = recommend_next_action(ProjectStage.IN_PROGRESS, {"in-progress": 1, "blocked-by-code": 2})
        assert "blocked" in action.lower()

    def test_in_progress_without_blocks(self) -> None:
        action = recommend_next_action(ProjectStage.IN_PROGRESS, {"in-progress": 2})
        assert "ydk task done" in action

    def test_reviewing_recommends_merge(self) -> None:
        action = recommend_next_action(ProjectStage.REVIEWING, {})
        assert "review" in action.lower() or "Merge" in action


class TestScanProject:
    def test_scan_empty_project(self, tmp_path: Path) -> None:
        result = scan_project(tmp_path)
        assert isinstance(result, NavigationStatus)
        assert result.stage == ProjectStage.EMPTY

    def test_scan_full_project(self, tmp_path: Path) -> None:
        ydk = tmp_path / ".ydk"
        (ydk / "specs").mkdir(parents=True)
        (ydk / "specs" / "api.md").write_text("# Spec")
        (ydk / "tasks").mkdir(parents=True)
        (ydk / "tasks" / "T-001.md").write_text("---\nstatus: open\n---\nTask")
        (ydk / "tasks" / "T-002.md").write_text("---\nstatus: done\n---\nDone")
        (ydk / "epics").mkdir(parents=True)
        (ydk / "epics" / "E-001.md").write_text("# Epic")
        (ydk / "stories").mkdir(parents=True)
        (ydk / "stories" / "S-001.md").write_text("# Story")

        result = scan_project(tmp_path)
        assert result.stage == ProjectStage.IN_PROGRESS
        assert result.spec_count == 1
        assert result.epic_count == 1
        assert result.story_count == 1
        assert result.task_counts == {"open": 1, "done": 1}

    def test_component_coverage(self, tmp_path: Path) -> None:
        ydk = tmp_path / ".ydk"
        (ydk / "components").mkdir(parents=True)
        (ydk / "components" / "order.yaml").write_text("id: order")
        (ydk / "components" / "user.yaml").write_text("id: user")
        (ydk / "tasks").mkdir(parents=True)
        (ydk / "tasks" / "T-001.md").write_text("---\nstatus: open\n---\nUses order component")

        result = scan_project(tmp_path)
        assert result.component_coverage is not None
        assert result.component_coverage.total == 2
        assert result.component_coverage.referenced_by_tasks == 1
        assert result.component_coverage.orphaned == 1

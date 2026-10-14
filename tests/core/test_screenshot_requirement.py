"""Tests for the configurable screenshot-proof requirement."""

from pathlib import Path

from ydk.core.task_lifecycle import TaskLifecycle
from ydk.models.pm import TaskDetail

UI_PATTERNS = ["ydk:page:*", "ydk:component:*"]


def _task(refs: list[str]) -> TaskDetail:
    return TaskDetail(title="t", component_refs=refs)


def test_default_route_requires_screenshot() -> None:
    assert TaskLifecycle._task_has_ui_components(_task(["ydk:route:api/healthz"])) is True


def test_default_page_requires_screenshot() -> None:
    assert TaskLifecycle._task_has_ui_components(_task(["ydk:page:ui/main"])) is True


def test_backend_route_exempt_with_ui_patterns() -> None:
    assert TaskLifecycle._task_has_ui_components(_task(["ydk:route:api/healthz"]), UI_PATTERNS) is False


def test_page_still_required_with_ui_patterns() -> None:
    assert TaskLifecycle._task_has_ui_components(_task(["ydk:page:ui/main"]), UI_PATTERNS) is True


def test_component_required_with_ui_patterns() -> None:
    assert TaskLifecycle._task_has_ui_components(_task(["ydk:component:button"]), UI_PATTERNS) is True


def test_no_refs() -> None:
    assert TaskLifecycle._task_has_ui_components(_task([])) is False


def test_patterns_read_from_config_file(tmp_path: Path) -> None:
    (tmp_path / ".ydk").mkdir()
    (tmp_path / ".ydk" / "config.yaml").write_text(
        "project:\n  name: x\nproof:\n  screenshot_ref_patterns:\n    - 'ydk:page:*'\n", encoding="utf-8"
    )
    lc = TaskLifecycle(None, None, None, None, project_root=tmp_path)  # ty: ignore[invalid-argument-type]
    assert lc._screenshot_ref_patterns() == ["ydk:page:*"]


def test_patterns_default_without_config(tmp_path: Path) -> None:
    lc = TaskLifecycle(None, None, None, None, project_root=tmp_path)  # ty: ignore[invalid-argument-type]
    assert lc._screenshot_ref_patterns() == ["ydk:page:*", "ydk:route:*"]

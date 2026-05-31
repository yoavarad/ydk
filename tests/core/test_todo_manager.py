"""Tests for odk.core.todo_manager — TODO tracking and verification."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from odk.core.todo_manager import TodoError, TodoManager
from odk.models.todo import TodoStatus


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Create a minimal project structure."""
    (tmp_path / ".odk").mkdir()
    return tmp_path


@pytest.fixture
def mgr(project: Path) -> TodoManager:
    return TodoManager(project)


# --- register ---


def test_register_creates_id(mgr: TodoManager) -> None:
    todo_id = mgr.register(file="app/service.py", line=10, method="Service.create")
    assert todo_id == "ODK-TODO-001"


def test_register_increments_id(mgr: TodoManager) -> None:
    mgr.register(file="a.py", line=1, method="A.x")
    mgr.register(file="b.py", line=2, method="B.y")
    third = mgr.register(file="c.py", line=3, method="C.z")
    assert third == "ODK-TODO-003"


def test_register_saves_to_yaml(mgr: TodoManager, project: Path) -> None:
    mgr.register(file="app/service.py", line=10, method="Service.create", description="Impl create")
    registry_path = project / ".odk" / "todos.yaml"
    assert registry_path.exists()
    content = registry_path.read_text()
    assert "ODK-TODO-001" in content
    assert "app/service.py" in content


def test_register_with_component_refs(mgr: TodoManager) -> None:
    todo_id = mgr.register(
        file="app/service.py",
        line=10,
        method="Service.create",
        component_refs=["odk:entity:orders/Order"],
    )
    item = mgr.get(todo_id)
    assert item.component_refs == ["odk:entity:orders/Order"]


# --- list ---


def test_list_all(mgr: TodoManager) -> None:
    mgr.register(file="a.py", line=1, method="A.x")
    mgr.register(file="b.py", line=2, method="B.y")
    items = mgr.list_todos()
    assert len(items) == 2


def test_list_filtered_by_status(mgr: TodoManager) -> None:
    mgr.register(file="a.py", line=1, method="A.x")
    id2 = mgr.register(file="b.py", line=2, method="B.y")
    mgr.start(id2)
    open_items = mgr.list_todos(status="open")
    assert len(open_items) == 1
    assert open_items[0].status == TodoStatus.OPEN


def test_list_empty_registry(mgr: TodoManager) -> None:
    assert mgr.list_todos() == []


# --- get ---


def test_get_existing(mgr: TodoManager) -> None:
    todo_id = mgr.register(file="a.py", line=5, method="A.do_thing")
    item = mgr.get(todo_id)
    assert item.id == todo_id
    assert item.file == "a.py"
    assert item.method == "A.do_thing"


def test_get_not_found(mgr: TodoManager) -> None:
    with pytest.raises(TodoError, match="TODO not found"):
        mgr.get("ODK-TODO-999")


# --- assign ---


def test_assign_links_task(mgr: TodoManager) -> None:
    todo_id = mgr.register(file="a.py", line=1, method="A.x")
    mgr.assign(todo_id, "T-042")
    item = mgr.get(todo_id)
    assert item.task_id == "T-042"


def test_assign_not_found(mgr: TodoManager) -> None:
    with pytest.raises(TodoError, match="TODO not found"):
        mgr.assign("ODK-TODO-999", "T-001")


# --- start ---


def test_start_changes_status(mgr: TodoManager) -> None:
    todo_id = mgr.register(file="a.py", line=1, method="A.x")
    mgr.start(todo_id)
    item = mgr.get(todo_id)
    assert item.status == TodoStatus.IN_PROGRESS


# --- done ---


def test_done_marks_complete(mgr: TodoManager, project: Path) -> None:
    # Create a file WITHOUT NotImplementedError (resolved)
    src = project / "app" / "service.py"
    src.parent.mkdir(parents=True)
    src.write_text("def create(self):\n    return self._repo.save()\n")
    todo_id = mgr.register(file="app/service.py", line=1, method="Service.create")
    mgr.done(todo_id)
    item = mgr.get(todo_id)
    assert item.status == TodoStatus.DONE


def test_done_fails_if_not_implemented_present(mgr: TodoManager, project: Path) -> None:
    src = project / "app" / "service.py"
    src.parent.mkdir(parents=True)
    src.write_text("def create(self):\n    raise NotImplementedError  # ODK-TODO-001: Impl create\n")
    todo_id = mgr.register(file="app/service.py", line=2, method="Service.create")
    with pytest.raises(TodoError, match="NotImplementedError still present"):
        mgr.done(todo_id)


# --- verify_done ---


def test_verify_done_true_when_resolved(mgr: TodoManager, project: Path) -> None:
    src = project / "app" / "service.py"
    src.parent.mkdir(parents=True)
    src.write_text("def create(self):\n    return 42\n")
    todo_id = mgr.register(file="app/service.py", line=1, method="Service.create")
    assert mgr.verify_done(todo_id) is True


def test_verify_done_false_when_still_present(mgr: TodoManager, project: Path) -> None:
    src = project / "app" / "service.py"
    src.parent.mkdir(parents=True)
    src.write_text("def create(self):\n    raise NotImplementedError  # ODK-TODO-001: Impl\n")
    todo_id = mgr.register(file="app/service.py", line=2, method="Service.create")
    assert mgr.verify_done(todo_id) is False


def test_verify_done_true_when_file_removed(mgr: TodoManager) -> None:
    todo_id = mgr.register(file="nonexistent/file.py", line=1, method="X.y")
    assert mgr.verify_done(todo_id) is True


def test_verify_done_not_found(mgr: TodoManager) -> None:
    with pytest.raises(TodoError, match="TODO not found"):
        mgr.verify_done("ODK-TODO-999")


# --- coverage ---


def test_coverage_empty(mgr: TodoManager) -> None:
    stats = mgr.coverage()
    assert stats == {"total": 0, "open": 0, "in_progress": 0, "done": 0, "percentage": 0.0}


def test_coverage_mixed(mgr: TodoManager, project: Path) -> None:
    # Register 3 TODOs
    mgr.register(file="a.py", line=1, method="A.x")
    id2 = mgr.register(file="b.py", line=1, method="B.y")
    id3 = mgr.register(file="c.py", line=1, method="C.z")

    mgr.start(id2)

    # Create a resolved file for id3
    src = project / "c.py"
    src.write_text("def z(self):\n    return 1\n")
    mgr.done(id3)

    stats = mgr.coverage()
    assert stats["total"] == 3
    assert stats["open"] == 1
    assert stats["in_progress"] == 1
    assert stats["done"] == 1
    assert stats["percentage"] == 33.3


# --- scan_file ---


def test_scan_file_finds_not_implemented(mgr: TodoManager, project: Path) -> None:
    src = project / "app" / "strategy.py"
    src.parent.mkdir(parents=True)
    src.write_text(
        "class StrategyService:\n"
        "    def create(self, data):\n"
        "        raise NotImplementedError  # ODK-TODO-001: Impl create\n"
        "\n"
        "    def update(self, data):\n"
        "        raise NotImplementedError  # ODK-TODO-002: Impl update\n"
    )
    results = mgr.scan_file("app/strategy.py")
    assert len(results) == 2
    assert results[0]["line"] == 3
    assert results[0]["method_name"] == "StrategyService.create"
    assert results[0]["comment"] == "Impl create"
    assert results[1]["line"] == 6
    assert results[1]["method_name"] == "StrategyService.update"
    assert results[1]["comment"] == "Impl update"


def test_scan_file_no_matches(mgr: TodoManager, project: Path) -> None:
    src = project / "clean.py"
    src.write_text("def hello():\n    return 'world'\n")
    assert mgr.scan_file("clean.py") == []


def test_scan_file_nonexistent(mgr: TodoManager) -> None:
    assert mgr.scan_file("does_not_exist.py") == []


def test_scan_file_bare_not_implemented(mgr: TodoManager, project: Path) -> None:
    src = project / "bare.py"
    src.write_text("def do_thing():\n    raise NotImplementedError\n")
    results = mgr.scan_file("bare.py")
    assert len(results) == 1
    assert results[0]["comment"] == ""
    assert results[0]["method_name"] == "do_thing"

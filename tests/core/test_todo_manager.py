"""Tests for ydk.core.todo_manager — TODO tracking and verification."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from ydk.core.todo_manager import TodoError, TodoManager
from ydk.models.todo import TodoStatus


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Create a minimal project structure."""
    (tmp_path / ".ydk").mkdir()
    return tmp_path


@pytest.fixture
def mgr(project: Path) -> TodoManager:
    return TodoManager(project)


# --- register ---


def test_register_creates_id(mgr: TodoManager) -> None:
    todo_id = mgr.register(file="app/service.py", line=10, method="Service.create")
    assert todo_id == "YDK-TODO-001"


def test_register_increments_id(mgr: TodoManager) -> None:
    mgr.register(file="a.py", line=1, method="A.x")
    mgr.register(file="b.py", line=2, method="B.y")
    third = mgr.register(file="c.py", line=3, method="C.z")
    assert third == "YDK-TODO-003"


def test_register_same_location_is_deduplicated(mgr: TodoManager) -> None:
    first = mgr.register(file="main.go", line=7, method="<unknown>")
    second = mgr.register(file="main.go", line=7, method="<unknown>")
    assert first == second
    assert len(mgr.list_todos()) == 1


def test_register_same_location_refreshes_details(mgr: TodoManager) -> None:
    todo_id = mgr.register(file="main.go", line=7, method="<unknown>", description="old")
    mgr.register(file="main.go", line=7, method="Svc.Do", description="new")
    item = mgr.get(todo_id)
    assert (item.method, item.description) == ("Svc.Do", "new")


def test_register_same_location_after_done_creates_new(mgr: TodoManager, project: Path) -> None:
    src = project / "app" / "service.py"
    src.parent.mkdir(parents=True)
    src.write_text("def create(self):\n    return 1\n")
    first = mgr.register(file="app/service.py", line=1, method="Service.create")
    mgr.done(first)
    assert mgr.register(file="app/service.py", line=1, method="Service.create") != first


def test_register_saves_to_yaml(mgr: TodoManager, project: Path) -> None:
    mgr.register(file="app/service.py", line=10, method="Service.create", description="Impl create")
    registry_path = project / ".ydk" / "todos.yaml"
    assert registry_path.exists()
    content = registry_path.read_text()
    assert "YDK-TODO-001" in content
    assert "app/service.py" in content


def test_register_with_component_refs(mgr: TodoManager) -> None:
    todo_id = mgr.register(
        file="app/service.py",
        line=10,
        method="Service.create",
        component_refs=["ydk:entity:orders/Order"],
    )
    item = mgr.get(todo_id)
    assert item.component_refs == ["ydk:entity:orders/Order"]


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
        mgr.get("YDK-TODO-999")


# --- assign ---


def test_assign_links_task(mgr: TodoManager) -> None:
    todo_id = mgr.register(file="a.py", line=1, method="A.x")
    mgr.assign(todo_id, "T-042")
    item = mgr.get(todo_id)
    assert item.task_id == "T-042"


def test_assign_not_found(mgr: TodoManager) -> None:
    with pytest.raises(TodoError, match="TODO not found"):
        mgr.assign("YDK-TODO-999", "T-001")


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
    src.write_text("def create(self):\n    raise NotImplementedError  # YDK-TODO-001: Impl create\n")
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
    src.write_text("def create(self):\n    raise NotImplementedError  # YDK-TODO-001: Impl\n")
    todo_id = mgr.register(file="app/service.py", line=2, method="Service.create")
    assert mgr.verify_done(todo_id) is False


def test_verify_done_true_when_file_removed(mgr: TodoManager) -> None:
    todo_id = mgr.register(file="nonexistent/file.py", line=1, method="X.y")
    assert mgr.verify_done(todo_id) is True


def test_verify_done_not_found(mgr: TodoManager) -> None:
    with pytest.raises(TodoError, match="TODO not found"):
        mgr.verify_done("YDK-TODO-999")


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
        "        raise NotImplementedError  # YDK-TODO-001: Impl create\n"
        "\n"
        "    def update(self, data):\n"
        "        raise NotImplementedError  # YDK-TODO-002: Impl update\n"
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


# --- per-language markers ---


def test_verify_done_go_panic_still_present(mgr: TodoManager, project: Path) -> None:
    src = project / "svc.go"
    src.write_text('package svc\n\nfunc Run() {\n\tpanic("not implemented") // YDK-TODO-001: impl\n}\n')
    todo_id = mgr.register(file="svc.go", line=4, method="Run")
    assert mgr.verify_done(todo_id) is False
    with pytest.raises(TodoError):
        mgr.done(todo_id)
    src.write_text("package svc\n\nfunc Run() {\n\treturn\n}\n")
    mgr.done(todo_id)


def test_verify_done_go_ydk_todo_panic(mgr: TodoManager, project: Path) -> None:
    src = project / "svc.go"
    src.write_text('package svc\n\nfunc Run() {\n\tpanic("YDK-TODO-001: impl Run")\n}\n')
    todo_id = mgr.register(file="svc.go", line=4, method="Run")
    assert mgr.verify_done(todo_id) is False


def test_verify_done_cs_throw_still_present(mgr: TodoManager, project: Path) -> None:
    src = project / "Foo.cs"
    src.write_text("class Foo {\n  void Run() {\n    throw new NotImplementedException();\n  }\n}\n")
    todo_id = mgr.register(file="Foo.cs", line=3, method="Run")
    assert mgr.verify_done(todo_id) is False
    src.write_text("class Foo {\n  void Run() {\n  }\n}\n")
    assert mgr.verify_done(todo_id) is True


def test_slash_comment_marker_recognized() -> None:
    from ydk.core.todo_manager import _TODO_COMMENT_RE

    m = _TODO_COMMENT_RE.search('\tpanic("x") // YDK-TODO-001: do it')
    assert m is not None
    assert m.group(2) == "do it"


# --- reconcile ---


def _marker(line: int, method: str = "Svc.run", description: str = "") -> dict:
    return {"line": line, "method": method, "description": description}


def test_reconcile_moved_marker_updates_line_keeps_id(mgr: TodoManager) -> None:
    todo_id = mgr.register(file="a.py", line=3, method="Svc.run", description="impl run")
    mgr.reconcile("a.py", [_marker(9, "Svc.run", "impl run")])
    todos = mgr.list_todos()
    assert len(todos) == 1
    assert (todos[0].id, todos[0].line, todos[0].status) == (todo_id, 9, TodoStatus.OPEN)


def test_reconcile_removed_marker_is_resolved(mgr: TodoManager) -> None:
    keep = mgr.register(file="a.py", line=3, method="Svc.a")
    gone = mgr.register(file="a.py", line=8, method="Svc.b")
    mgr.reconcile("a.py", [_marker(3, "Svc.a")])
    assert mgr.get(keep).status == TodoStatus.OPEN
    assert mgr.get(gone).status == TodoStatus.DONE


def test_reconcile_new_marker_registered(mgr: TodoManager) -> None:
    mgr.reconcile("a.py", [_marker(4, "Svc.new")])
    todos = mgr.list_todos()
    assert [(t.file, t.line, t.method) for t in todos] == [("a.py", 4, "Svc.new")]


def test_reconcile_ignores_other_files_and_done(mgr: TodoManager) -> None:
    other = mgr.register(file="b.py", line=1, method="X.y")
    mgr.reconcile("a.py", [])
    assert mgr.get(other).status == TodoStatus.OPEN


def test_reconcile_same_method_twice_moves_each(mgr: TodoManager) -> None:
    mgr.register(file="a.go", line=3, method="<unknown>")
    mgr.register(file="a.go", line=6, method="<unknown>")
    mgr.reconcile("a.go", [_marker(5, "<unknown>"), _marker(8, "<unknown>")])
    assert sorted(t.line for t in mgr.list_todos()) == [5, 8]
    assert all(t.status == TodoStatus.OPEN for t in mgr.list_todos())


def test_reconcile_different_method_on_same_line_gets_new_id(mgr: TodoManager) -> None:
    old = mgr.register(file="a.py", line=5, method="Svc.old", description="impl old")
    mgr.reconcile("a.py", [_marker(5, "Svc.other", "impl other")])
    assert mgr.get(old).status == TodoStatus.DONE
    fresh = [t for t in mgr.list_todos() if t.id != old]
    assert [(t.method, t.line, t.status) for t in fresh] == [("Svc.other", 5, TodoStatus.OPEN)]


def test_reconcile_unknown_method_different_text_on_same_line_gets_new_id(mgr: TodoManager) -> None:
    old = mgr.register(file="a.go", line=5, method="<unknown>", description="first")
    mgr.reconcile("a.go", [_marker(5, "<unknown>", "second")])
    assert mgr.get(old).status == TodoStatus.DONE
    assert len(mgr.list_todos()) == 2


def test_reconcile_new_marker_records_component_refs(mgr: TodoManager) -> None:
    mgr.reconcile("a.go", [{**_marker(4, "Svc.Run"), "component_refs": ["ydk:contract:orders/Svc"]}])
    assert mgr.list_todos()[0].component_refs == ["ydk:contract:orders/Svc"]


def test_reconcile_matched_marker_updates_component_refs(mgr: TodoManager) -> None:
    todo_id = mgr.register(file="a.go", line=4, method="Svc.Run")
    mgr.reconcile("a.go", [{**_marker(4, "Svc.Run"), "component_refs": ["ydk:contract:orders/Svc"]}])
    assert mgr.get(todo_id).component_refs == ["ydk:contract:orders/Svc"]


def test_reconcile_empty_marker_refs_keep_existing(mgr: TodoManager) -> None:
    todo_id = mgr.register(file="a.go", line=4, method="Svc.Run", component_refs=["ydk:contract:orders/Manual"])
    mgr.reconcile("a.go", [_marker(4, "Svc.Run")])
    mgr.reconcile("a.go", [{**_marker(4, "Svc.Run"), "component_refs": []}])
    assert mgr.get(todo_id).component_refs == ["ydk:contract:orders/Manual"]


def test_reconcile_non_empty_marker_refs_replace_existing(mgr: TodoManager) -> None:
    todo_id = mgr.register(file="a.go", line=4, method="Svc.Run", component_refs=["ydk:contract:orders/Old"])
    mgr.reconcile("a.go", [{**_marker(4, "Svc.Run"), "component_refs": ["ydk:contract:orders/New"]}])
    assert mgr.get(todo_id).component_refs == ["ydk:contract:orders/New"]

"""Go-stack behaviour of TaskLifecycle task-done checks (test derivation, skip check, TODO labels).

Uses real temp git repos and the real TodoManager; only the PM repo,
worktree manager and verifier (system boundaries for these checks) are mocked.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import yaml

from ydk.core.events import EventBus
from ydk.core.task_lifecycle import TaskLifecycle
from ydk.core.todo_manager import TodoManager

if TYPE_CHECKING:
    from pathlib import Path


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _write_config(root: Path, stack: str, go: dict | None = None) -> None:
    data: dict = {"project": {"name": "p", "stack": stack}}
    if go is not None:
        data["verification"] = {"go": go}
    (root / ".ydk").mkdir(exist_ok=True)
    (root / ".ydk" / "config.yaml").write_text(yaml.dump(data), encoding="utf-8")


def _lifecycle(root: Path) -> TaskLifecycle:
    wt = MagicMock()
    wt.get_worktree_path.return_value = None
    return TaskLifecycle(
        repo=MagicMock(),
        events=EventBus(),
        worktree_mgr=wt,
        verifier=MagicMock(),
        project_root=root,
    )


@pytest.fixture
def go_repo(tmp_path: Path) -> Path:
    """Git repo on branch ``main`` with a go stack config, then a ``feature`` branch checked out."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    _write_config(tmp_path, "go")
    (tmp_path / "go.mod").write_text("module example.com/m\n\ngo 1.22\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    return tmp_path


def _commit(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(root, "add", rel)
    _git(root, "commit", "-q", "-m", f"add {rel}")


_UNREASONED = 'package svc\n\nimport "testing"\n\nfunc TestFoo(t *testing.T) {\n\tt.Skip()\n}\n'
_REASONED = 'package svc\n\nimport "testing"\n\nfunc TestFoo(t *testing.T) {\n\tt.Skip("needs db")\n}\n'


class TestDeriveTestFiles:
    def test_go_maps_to_same_dir_test_file(self, go_repo: Path) -> None:
        result = _lifecycle(go_repo)._derive_test_files(["internal/svc/foo.go"])
        assert result == ["internal/svc/foo_test.go"]

    def test_go_test_file_maps_to_itself(self, go_repo: Path) -> None:
        result = _lifecycle(go_repo)._derive_test_files(["internal/svc/foo_test.go"])
        assert result == ["internal/svc/foo_test.go"]

    def test_python_mapping_unchanged(self, tmp_path: Path) -> None:
        result = _lifecycle(tmp_path)._derive_test_files(["app/core/services/foo.py"])
        assert result == ["tests/unit/test_foo.py", "tests/test_foo.py"]


class TestGoSkipCheck:
    def test_committed_unreasoned_skip_in_changed_test_fails(self, go_repo: Path) -> None:
        _commit(go_repo, "internal/svc/foo_test.go", _UNREASONED)
        warnings = _lifecycle(go_repo)._check_xfail_removed("T-001", [])
        assert len(warnings) == 1
        assert "internal/svc/foo_test.go:6" in warnings[0]
        assert "t.Skip()" in warnings[0]

    def test_reasoned_skip_passes(self, go_repo: Path) -> None:
        _commit(go_repo, "internal/svc/foo_test.go", _REASONED)
        assert _lifecycle(go_repo)._check_xfail_removed("T-001", []) == []

    def test_unchanged_derived_test_with_old_skip_passes(self, go_repo: Path) -> None:
        _commit(go_repo, "internal/svc/foo_test.go", _UNREASONED)
        _git(go_repo, "checkout", "-q", "-B", "main")  # skip predates the task: no diff vs base
        assert _lifecycle(go_repo)._check_xfail_removed("T-001", ["internal/svc/foo.go"]) == []

    def test_preexisting_skip_in_touched_file_passes(self, go_repo: Path) -> None:
        _commit(go_repo, "internal/svc/foo_test.go", _UNREASONED)
        _git(go_repo, "checkout", "-q", "-B", "main")
        _git(go_repo, "checkout", "-q", "-B", "feature")
        _commit(go_repo, "internal/svc/foo_test.go", _UNREASONED + '\nfunc TestBar(t *testing.T) {\n\tt.Log("x")\n}\n')
        assert _lifecycle(go_repo)._check_xfail_removed("T-001", ["internal/svc/foo.go"]) == []

    def test_added_skip_in_preexisting_file_fails_with_new_line_number(self, go_repo: Path) -> None:
        _commit(go_repo, "internal/svc/foo_test.go", _REASONED)
        _git(go_repo, "checkout", "-q", "-B", "main")
        _git(go_repo, "checkout", "-q", "-B", "feature")
        _commit(go_repo, "internal/svc/foo_test.go", _REASONED + "\nfunc TestBar(t *testing.T) {\n\tt.Skip()\n}\n")
        warnings = _lifecycle(go_repo)._check_xfail_removed("T-001", [])
        assert len(warnings) == 1
        assert "internal/svc/foo_test.go:10" in warnings[0]

    def test_untracked_new_test_file_is_scanned(self, go_repo: Path) -> None:
        (go_repo / "pkg").mkdir()
        (go_repo / "pkg" / "new_test.go").write_text(_UNREASONED, encoding="utf-8")
        warnings = _lifecycle(go_repo)._check_xfail_removed("T-001", [])
        assert len(warnings) == 1
        assert "pkg/new_test.go:6" in warnings[0]

    def test_untracked_unicode_test_file_is_scanned(self, go_repo: Path) -> None:
        (go_repo / "pé_test.go").write_text(_UNREASONED, encoding="utf-8")
        assert len(_lifecycle(go_repo)._check_xfail_removed("T-001", [])) == 1

    def test_committed_unicode_test_file_is_scanned(self, go_repo: Path) -> None:
        _commit(go_repo, "pé_test.go", _UNREASONED)
        assert len(_lifecycle(go_repo)._check_xfail_removed("T-001", [])) == 1

    def test_formfeed_in_comment_keeps_line_numbers(self, go_repo: Path) -> None:
        _commit(go_repo, "x_test.go", "package x\n// a\fb\nfunc TestX(t *testing.T) {\n\tt.Skip()\n}\n")
        warnings = _lifecycle(go_repo)._check_xfail_removed("T-001", [])
        assert len(warnings) == 1
        assert "x_test.go:4" in warnings[0]

    def test_project_root_in_repo_subdir(self, go_repo: Path) -> None:
        sub = go_repo / "svc"
        sub.mkdir()
        _write_config(sub, "go")
        _commit(go_repo, "svc/x_test.go", _UNREASONED)
        warnings = _lifecycle(sub)._check_xfail_removed("T-001", [])
        assert len(warnings) == 1
        assert "x_test.go:6" in warnings[0]

    @pytest.mark.parametrize(
        "call",
        [
            't.Skip("")',
            "t.SkipNow()",
            't.Skipf("")',
            "b.Skip()",
            "tb.SkipNow()",
            "f.Skip( )",
            "t.Skip(\n\t)",
            "t.Skip(\n\t\t``,\n\t)",
            "s.T().Skip()",
            "s.T().SkipNow()",
            "suite.Require().T().Skip()",
            "helper.Skip()",
        ],
    )
    def test_unreasoned_variants_fail(self, go_repo: Path, call: str) -> None:
        _commit(go_repo, "x_test.go", f"package x\n\nfunc TestX(t *testing.T) {{\n\t{call}\n}}\n")
        assert len(_lifecycle(go_repo)._check_xfail_removed("T-001", [])) == 1

    @pytest.mark.parametrize(
        "body",
        [
            '\tt.Skipf("needs %s", "db")',
            "\t// t.Skip()",
            "\tx := 1 // t.SkipNow()",
            "\t/* t.Skip() */",
            "\t/*\n\tt.Skip()\n\t*/",
            '\ts := "t.Skip()"',
            '\tt.Skip(\n\t\t"needs db",\n\t)',
            '\ts.T().Skip("needs db")',
            "\t// s.T().Skip()",
            "\tt.Skipped()",
        ],
    )
    def test_reasoned_or_commented_skips_pass(self, go_repo: Path, body: str) -> None:
        _commit(go_repo, "x_test.go", f"package x\n\nfunc TestX(t *testing.T) {{\n{body}\n}}\n")
        assert _lifecycle(go_repo)._check_xfail_removed("T-001", []) == []

    def test_skip_patterns_configurable(self, go_repo: Path) -> None:
        _write_config(go_repo, "go", go={"skip_patterns": []})
        _commit(go_repo, "internal/svc/foo_test.go", _UNREASONED)
        assert _lifecycle(go_repo)._check_xfail_removed("T-001", []) == []

    def test_custom_pattern_applies(self, go_repo: Path) -> None:
        _write_config(go_repo, "go", go={"skip_patterns": [r"t\.Skip\("]})
        _commit(go_repo, "internal/svc/foo_test.go", _REASONED)
        assert len(_lifecycle(go_repo)._check_xfail_removed("T-001", [])) == 1

    def test_python_stack_ignores_go_skips(self, go_repo: Path) -> None:
        _write_config(go_repo, "python-cli")
        _commit(go_repo, "internal/svc/foo_test.go", _UNREASONED)
        assert _lifecycle(go_repo)._check_xfail_removed("T-001", []) == []


class TestTodoResolutionLabel:
    def test_go_todo_warning_names_panic_marker(self, go_repo: Path) -> None:
        (go_repo / "svc.go").write_text(
            'package svc\n\nfunc Do() {\n\tpanic("not implemented") // YDK-TODO-001: do\n}\n', encoding="utf-8"
        )
        mgr = TodoManager(go_repo)
        todo_id = mgr.register("svc.go", 4, "Do")
        mgr.assign(todo_id, "T-001")
        warnings = _lifecycle(go_repo)._check_todo_resolution("T-001")
        assert warnings == [f'TODO {todo_id} still has panic("not implemented") in svc.go']

    def test_python_todo_warning_unchanged(self, tmp_path: Path) -> None:
        (tmp_path / "svc.py").write_text("def do():\n    raise NotImplementedError  # YDK-TODO-001: do\n")
        mgr = TodoManager(tmp_path)
        todo_id = mgr.register("svc.py", 2, "do")
        mgr.assign(todo_id, "T-001")
        warnings = _lifecycle(tmp_path)._check_todo_resolution("T-001")
        assert warnings == [f"TODO {todo_id} still has NotImplementedError in svc.py"]


def test_git_diff_failure_falls_back_to_all_go_tests(tmp_path: Path) -> None:
    """Outside a git repo the diff fails; every *_test.go (minus vendor/) is scanned instead."""
    _write_config(tmp_path, "go")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a_test.go").write_text(_UNREASONED, encoding="utf-8")
    (tmp_path / "vendor" / "x").mkdir(parents=True)
    (tmp_path / "vendor" / "x" / "b_test.go").write_text(_UNREASONED, encoding="utf-8")
    warnings = _lifecycle(tmp_path)._check_xfail_removed("T-001", [])
    assert len(warnings) == 1
    assert "pkg/a_test.go:6" in warnings[0]

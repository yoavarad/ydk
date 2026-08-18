"""Tests for scaffold state (hash tracking for idempotent ignition)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ydk.core.scaffold_state import ScaffoldState

if TYPE_CHECKING:
    from pathlib import Path


def test_new_file_is_modified(tmp_path: Path) -> None:
    """A file not yet tracked is always considered modified."""
    state = ScaffoldState(tmp_path / "state.yaml")
    assert state.is_modified("app/main.py", "print('hello')")


def test_unchanged_file_is_not_modified(tmp_path: Path) -> None:
    """After update, same content is not modified."""
    state = ScaffoldState(tmp_path / "state.yaml")
    state.update("app/main.py", "print('hello')")
    assert not state.is_modified("app/main.py", "print('hello')")


def test_changed_content_is_modified(tmp_path: Path) -> None:
    """Different content triggers modified."""
    state = ScaffoldState(tmp_path / "state.yaml")
    state.update("app/main.py", "print('hello')")
    assert state.is_modified("app/main.py", "print('world')")


def test_save_and_reload(tmp_path: Path) -> None:
    """Hashes survive save/reload cycle."""
    path = tmp_path / "state.yaml"
    state1 = ScaffoldState(path)
    state1.update("a.py", "content-a")
    state1.save()

    state2 = ScaffoldState(path)
    assert not state2.is_modified("a.py", "content-a")
    assert state2.is_modified("a.py", "content-b")


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    """save() creates missing parent directories."""
    path = tmp_path / "deep" / "nested" / "state.yaml"
    state = ScaffoldState(path)
    state.update("x.py", "x")
    state.save()
    assert path.exists()


def test_developer_owned_untracked_file(tmp_path: Path) -> None:
    """File that has never been tracked is not developer-owned."""
    state = ScaffoldState(tmp_path / "state.yaml")
    f = tmp_path / "app" / "models.py"
    f.parent.mkdir(parents=True)
    f.write_text("class Foo: pass\n")
    assert not state.is_developer_owned("app/models.py", tmp_path)


def test_developer_owned_modified_after_generation(tmp_path: Path) -> None:
    """File that was generated then modified by developer is developer-owned."""
    state = ScaffoldState(tmp_path / "state.yaml")
    f = tmp_path / "app" / "models.py"
    f.parent.mkdir(parents=True)
    original_content = "class Foo: pass\n"
    f.write_text(original_content)
    state.update("app/models.py", original_content)
    state.save()
    # Developer modifies the file
    f.write_text("class Foo:\n    bar = 42\n")
    assert state.is_developer_owned("app/models.py", tmp_path)


def test_developer_owned_unchanged_after_generation(tmp_path: Path) -> None:
    """File that matches its stored hash is not developer-owned."""
    state = ScaffoldState(tmp_path / "state.yaml")
    f = tmp_path / "app" / "models.py"
    f.parent.mkdir(parents=True)
    content = "class Foo: pass\n"
    f.write_text(content)
    state.update("app/models.py", content)
    state.save()
    assert not state.is_developer_owned("app/models.py", tmp_path)


def test_developer_owned_nonexistent_file(tmp_path: Path) -> None:
    """Non-existent file is not developer-owned."""
    state = ScaffoldState(tmp_path / "state.yaml")
    assert not state.is_developer_owned("nope.py", tmp_path)


def test_load_handles_empty_file(tmp_path: Path) -> None:
    """Loading an empty state file doesn't crash."""
    path = tmp_path / "state.yaml"
    path.write_text("")
    state = ScaffoldState(path)
    assert state.is_modified("any.py", "content")


def test_load_handles_corrupt_file(tmp_path: Path) -> None:
    """Loading a non-dict YAML doesn't crash."""
    path = tmp_path / "state.yaml"
    path.write_text("just a string\n")
    state = ScaffoldState(path)
    assert state.is_modified("any.py", "content")

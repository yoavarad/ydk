"""Tests for the spec evolution engine."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from odk.core.spec_evolution import SpecEvolutionEngine
from odk.models.change import ChangeMode, ChangeStatus

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def engine():
    return SpecEvolutionEngine()


@pytest.fixture
def project(tmp_path: Path):
    (tmp_path / "docs" / "changes").mkdir(parents=True)
    (tmp_path / "docs" / "specs").mkdir(parents=True)
    return tmp_path


# --- propose ---


def test_propose_creates_directory_structure(engine, project):
    info = engine.propose("add-websocket", "small", project)
    change_dir = project / "docs" / "changes" / "add-websocket"

    assert change_dir.is_dir()
    assert (change_dir / ".change.yaml").exists()
    assert (change_dir / "proposal.md").exists()
    assert (change_dir / "tasks.md").exists()
    assert (change_dir / "delta-specs").is_dir()
    assert not (change_dir / "design.md").exists()

    assert info.name == "add-websocket"
    assert info.mode == ChangeMode.SMALL
    assert info.status == ChangeStatus.ACTIVE


def test_propose_major_includes_design(engine, project):
    info = engine.propose("big-refactor", "major", project)
    change_dir = project / "docs" / "changes" / "big-refactor"

    assert (change_dir / "design.md").exists()
    assert info.mode == ChangeMode.MAJOR


def test_propose_duplicate_raises(engine, project):
    engine.propose("my-change", "small", project)
    with pytest.raises(FileExistsError, match="already exists"):
        engine.propose("my-change", "small", project)


def test_propose_invalid_mode_raises(engine, project):
    with pytest.raises(ValueError, match="'invalid' is not a valid ChangeMode"):
        engine.propose("bad-mode", "invalid", project)


def test_propose_yaml_content(engine, project):
    engine.propose("test-yaml", "major", project)
    data = yaml.safe_load((project / "docs" / "changes" / "test-yaml" / ".change.yaml").read_text())
    assert data["name"] == "test-yaml"
    assert data["mode"] == "major"
    assert data["status"] == "active"


# --- list_changes ---


def test_list_changes_empty(engine, project):
    changes = engine.list_changes(project, "all")
    assert changes == []


def test_list_changes_active(engine, project):
    engine.propose("alpha", "small", project)
    engine.propose("beta", "major", project)

    changes = engine.list_changes(project, "active")
    assert len(changes) == 2
    names = {c.name for c in changes}
    assert names == {"alpha", "beta"}


def test_list_changes_filters_by_status(engine, project):
    engine.propose("only-active", "small", project)
    changes = engine.list_changes(project, "archived")
    assert len(changes) == 0


# --- get_change_status ---


def test_status_small_change_initial(engine, project):
    engine.propose("check-me", "small", project)
    status = engine.get_change_status("check-me", project)

    assert "proposal.md" in status.present
    assert "tasks.md" in status.present
    assert "delta-specs" in status.missing
    assert set(status.required) == {"proposal.md", "delta-specs", "tasks.md"}


def test_status_with_delta_specs(engine, project):
    engine.propose("with-deltas", "small", project)
    delta_dir = project / "docs" / "changes" / "with-deltas" / "delta-specs"
    (delta_dir / "api.md").write_text("## ADDED\n### New thing\ncontent")

    status = engine.get_change_status("with-deltas", project)
    assert "delta-specs" in status.present


def test_status_not_found(engine, project):
    with pytest.raises(FileNotFoundError, match="not found"):
        engine.get_change_status("nonexistent", project)


# --- archive ---


def test_archive_moves_to_archive_dir(engine, project):
    engine.propose("archive-me", "small", project)
    result = engine.archive("archive-me", project)

    assert not (project / "docs" / "changes" / "archive-me").exists()
    assert "archive" in result.archive_path
    assert "archive-me" in result.archive_path


def test_archive_applies_delta_operations(engine, project):
    engine.propose("with-ops", "small", project)
    (project / "docs" / "specs" / "api.md").write_text("# API\n\n### GET /users\n\nList users.\n")

    delta_dir = project / "docs" / "changes" / "with-ops" / "delta-specs"
    (delta_dir / "api.md").write_text("""\
> Target: api.md

## ADDED

### POST /users

Create a user.
""")

    result = engine.archive("with-ops", project)
    assert result.operations_applied == 1
    assert "api.md" in result.target_files_modified

    spec_content = (project / "docs" / "specs" / "api.md").read_text()
    assert "### POST /users" in spec_content
    assert "Create a user." in spec_content


def test_archive_updates_yaml_status(engine, project):
    engine.propose("status-check", "small", project)
    result = engine.archive("status-check", project)

    archive_path = project / result.archive_path
    data = yaml.safe_load((archive_path / ".change.yaml").read_text())
    assert data["status"] == "archived"


def test_archive_not_found(engine, project):
    with pytest.raises(FileNotFoundError):
        engine.archive("ghost", project)


def test_archive_creates_spec_if_missing(engine, project):
    engine.propose("new-spec", "small", project)
    delta_dir = project / "docs" / "changes" / "new-spec" / "delta-specs"
    (delta_dir / "new-feature.md").write_text("""\
> Target: new-feature.md

## ADDED

### Feature A

Description of feature A.
""")

    engine.archive("new-spec", project)
    assert (project / "docs" / "specs" / "new-feature.md").exists()


# --- diff ---


def test_diff_returns_operations(engine, project):
    engine.propose("diff-test", "small", project)
    delta_dir = project / "docs" / "changes" / "diff-test" / "delta-specs"
    (delta_dir / "api.md").write_text("""\
> Target: api.md

## ADDED

### POST /items

New endpoint.

## REMOVED

### DELETE /old
""")

    ops = engine.diff("diff-test", project)
    assert len(ops) == 2


def test_diff_empty_deltas(engine, project):
    engine.propose("empty-diff", "small", project)
    ops = engine.diff("empty-diff", project)
    assert ops == []


def test_diff_not_found(engine, project):
    with pytest.raises(FileNotFoundError):
        engine.diff("nope", project)


# --- round-trip: propose -> populate deltas -> archive -> list archived ---


def test_full_lifecycle(engine, project):
    engine.propose("lifecycle", "major", project)

    (project / "docs" / "specs" / "api.md").write_text("# API\n\n### GET /health\n\nHealth check.\n")

    delta_dir = project / "docs" / "changes" / "lifecycle" / "delta-specs"
    (delta_dir / "api.md").write_text("""\
> Target: api.md

## ADDED

### GET /version

Returns version info.

## MODIFIED

### GET /health

Health check with detailed status.
""")

    ops = engine.diff("lifecycle", project)
    assert len(ops) == 2

    result = engine.archive("lifecycle", project)
    assert result.operations_applied == 2

    spec = (project / "docs" / "specs" / "api.md").read_text()
    assert "### GET /version" in spec
    assert "detailed status" in spec
    assert "Health check." not in spec

    archived = engine.list_changes(project, "archived")
    assert len(archived) == 1
    assert archived[0].name == "lifecycle"

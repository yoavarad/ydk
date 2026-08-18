"""Tests for the delta spec parser."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ydk.core.delta_parser import apply_operations_to_spec, parse_delta_directory, parse_delta_file
from ydk.models.change import DeltaType

if TYPE_CHECKING:
    from pathlib import Path


# --- parse_delta_file ---


def test_parse_empty_content():
    assert parse_delta_file("") == []
    assert parse_delta_file("   \n\n  ") == []


def test_parse_added_section():
    content = """\
> Target: specs/api.md

## ADDED

### POST /users

Creates a new user account.
"""
    ops = parse_delta_file(content)
    assert len(ops) == 1
    assert ops[0].delta_type == DeltaType.ADDED
    assert ops[0].target_file == "specs/api.md"
    assert ops[0].section_heading == "POST /users"
    assert "Creates a new user account." in ops[0].content


def test_parse_modified_section():
    content = """\
> Target: specs/api.md

## MODIFIED

### GET /users

Now returns paginated results.
"""
    ops = parse_delta_file(content)
    assert len(ops) == 1
    assert ops[0].delta_type == DeltaType.MODIFIED
    assert ops[0].section_heading == "GET /users"


def test_parse_removed_section():
    content = """\
> Target: specs/api.md

## REMOVED

### DELETE /legacy
"""
    ops = parse_delta_file(content)
    assert len(ops) == 1
    assert ops[0].delta_type == DeltaType.REMOVED
    assert ops[0].section_heading == "DELETE /legacy"
    assert ops[0].content == ""


def test_parse_multiple_sections():
    content = """\
> Target: specs/api.md

## ADDED

### POST /webhooks

Register a webhook.

### GET /webhooks

List webhooks.

## MODIFIED

### GET /users

Updated response format.

## REMOVED

### DELETE /v1/old
"""
    ops = parse_delta_file(content)
    assert len(ops) == 4
    types = [op.delta_type for op in ops]
    assert types == [DeltaType.ADDED, DeltaType.ADDED, DeltaType.MODIFIED, DeltaType.REMOVED]


def test_parse_case_insensitive_sections():
    content = """\
> Target: specs/api.md

## Added

### New thing

Content here.
"""
    ops = parse_delta_file(content)
    assert len(ops) == 1
    assert ops[0].delta_type == DeltaType.ADDED


def test_parse_uses_default_target_when_no_target_directive():
    content = """\
## ADDED

### Something

Content.
"""
    ops = parse_delta_file(content, default_target="fallback")
    assert len(ops) == 1
    assert ops[0].target_file == "fallback"


# --- parse_delta_directory ---


def test_parse_delta_directory_reads_md_files(tmp_path: Path):
    delta_dir = tmp_path / "delta-specs"
    delta_dir.mkdir()
    (delta_dir / "api.md").write_text("""\
> Target: specs/api.md

## ADDED

### POST /new

New endpoint.
""")
    (delta_dir / "models.md").write_text("""\
> Target: specs/models.md

## MODIFIED

### User model

Added email field.
""")
    ops = parse_delta_directory(delta_dir)
    assert len(ops) == 2


def test_parse_delta_directory_nonexistent(tmp_path: Path):
    assert parse_delta_directory(tmp_path / "nope") == []


# --- apply_operations_to_spec ---


def test_apply_add_appends_to_spec():
    from ydk.models.change import DeltaOperation

    spec = "# API Spec\n\n### GET /users\n\nReturns all users.\n"
    ops = [
        DeltaOperation(
            delta_type=DeltaType.ADDED,
            target_file="api.md",
            section_heading="POST /users",
            content="Creates a user.",
        )
    ]
    result = apply_operations_to_spec(spec, ops)
    assert "### POST /users" in result
    assert "Creates a user." in result
    assert result.index("### GET /users") < result.index("### POST /users")


def test_apply_modify_replaces_block():
    from ydk.models.change import DeltaOperation

    spec = "# API\n\n### GET /users\n\nOld description.\n\n### GET /items\n\nItems list.\n"
    ops = [
        DeltaOperation(
            delta_type=DeltaType.MODIFIED,
            target_file="api.md",
            section_heading="GET /users",
            content="New description with pagination.",
        )
    ]
    result = apply_operations_to_spec(spec, ops)
    assert "New description with pagination." in result
    assert "Old description." not in result
    assert "### GET /items" in result


def test_apply_remove_deletes_block():
    from ydk.models.change import DeltaOperation

    spec = "# API\n\n### GET /users\n\nUsers list.\n\n### DELETE /legacy\n\nOld endpoint.\n"
    ops = [
        DeltaOperation(
            delta_type=DeltaType.REMOVED,
            target_file="api.md",
            section_heading="DELETE /legacy",
            content="",
        )
    ]
    result = apply_operations_to_spec(spec, ops)
    assert "### DELETE /legacy" not in result
    assert "Old endpoint." not in result
    assert "### GET /users" in result


def test_apply_modify_nonexistent_block_leaves_unchanged():
    from ydk.models.change import DeltaOperation

    spec = "# API\n\n### GET /users\n\nUsers.\n"
    ops = [
        DeltaOperation(
            delta_type=DeltaType.MODIFIED,
            target_file="api.md",
            section_heading="GET /nonexistent",
            content="Should not appear.",
        )
    ]
    result = apply_operations_to_spec(spec, ops)
    assert result == spec

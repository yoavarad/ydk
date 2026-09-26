"""Tests for ydk.core.task_ref -- shared batch-mapping task reference resolver."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from ydk.core.task_ref import resolve_task_ref
from ydk.repositories.github.tasks import _extract_issue_number

if TYPE_CHECKING:
    from pathlib import Path


def _write_mapping(root: Path, mapping: dict[str, str]) -> Path:
    ydk_dir = root / ".ydk"
    ydk_dir.mkdir(exist_ok=True)
    mapping_file = ydk_dir / "batch-mapping.json"
    mapping_file.write_text(json.dumps(mapping), encoding="utf-8")
    return mapping_file


@pytest.mark.parametrize(
    ("placeholder", "expected"),
    [
        ("T-001", "42"),
        ("t-001", "42"),
        ("S-001", "17"),
        ("E-001", "9"),
    ],
)
def test_mapped_placeholders_resolve_to_issue_number(tmp_path: Path, placeholder: str, expected: str) -> None:
    mapping_file = _write_mapping(tmp_path, {"T-001": "#42", "S-001": "#17", "E-001": "9"})

    resolved = resolve_task_ref(placeholder, mapping_file)

    assert resolved == expected
    assert _extract_issue_number(resolved) == int(expected)


@pytest.mark.parametrize(("raw", "expected"), [("12", "12"), ("#12", "12")])
def test_numeric_refs_normalize_without_mapping(tmp_path: Path, raw: str, expected: str) -> None:
    assert resolve_task_ref(raw, tmp_path / "missing.json") == expected


@pytest.mark.parametrize("raw", ["T-5e9dbd18", "QD-abc123", "T-12345678", "T-001"])
def test_unmapped_ids_pass_through_and_fail_strict_parse(tmp_path: Path, raw: str) -> None:
    mapping_file = _write_mapping(tmp_path, {"T-999": "#1"})

    resolved = resolve_task_ref(raw, mapping_file)

    assert resolved == raw
    with pytest.raises(ValueError, match=raw):
        _extract_issue_number(resolved)


def test_unmapped_hash_like_id_resolves_when_present_in_mapping(tmp_path: Path) -> None:
    mapping_file = _write_mapping(tmp_path, {"T-5e9dbd18": "#77"})

    assert resolve_task_ref("T-5e9dbd18", mapping_file) == "77"


def test_non_numeric_mapping_value_returned_as_is(tmp_path: Path) -> None:
    """Local-backend mappings (placeholder -> T-xxx id) are not rewritten."""
    mapping_file = _write_mapping(tmp_path, {"T-001": "T-abc123"})

    assert resolve_task_ref("T-001", mapping_file) == "T-abc123"


def test_invalid_mapping_json_is_ignored(tmp_path: Path) -> None:
    ydk_dir = tmp_path / ".ydk"
    ydk_dir.mkdir()
    mapping_file = ydk_dir / "batch-mapping.json"
    mapping_file.write_text("{not json", encoding="utf-8")

    assert resolve_task_ref("T-001", mapping_file) == "T-001"


def test_default_mapping_path_is_cwd_ydk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_mapping(tmp_path, {"S-002": "#5"})

    assert resolve_task_ref("S-002") == "5"

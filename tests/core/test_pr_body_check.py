"""Tests for the shared pr-body-validation helper (real bundled plugin)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ydk.core.pr_body_check import run_pr_body_validation
from ydk.core.verifier import Verifier

if TYPE_CHECKING:
    from pathlib import Path

GOOD_BODY = "## Summary\n\nDid it.\n\n## Test Plan\n\n```console\n$ pytest\nok\n```\n"


def test_passes_for_valid_body(tmp_path: Path) -> None:
    result = run_pr_body_validation(GOOD_BODY, [], tmp_path)
    assert result is not None
    assert result.passed is True


def test_fails_when_summary_missing(tmp_path: Path) -> None:
    result = run_pr_body_validation("no sections here", [], tmp_path)
    assert result is not None
    assert result.passed is False
    assert "FAIL:" in result.output


def test_changed_files_feed_screenshot_rule(tmp_path: Path) -> None:
    result = run_pr_body_validation(GOOD_BODY, ["web/App.tsx"], tmp_path)
    assert result is not None
    assert result.passed is False
    assert "screenshot" in result.output.lower()


def test_returns_none_when_plugin_missing(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    verifier = Verifier(project_root=tmp_path, global_verifications=empty, project_verifications=empty)
    assert run_pr_body_validation(GOOD_BODY, [], tmp_path, verifier=verifier) is None

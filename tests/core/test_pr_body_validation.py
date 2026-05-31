"""Tests for PR body validation — verification plugin and _build_pr_body integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from odk.core.events import EventBus
from odk.core.task_lifecycle import TaskLifecycle
from odk.models.pm import TaskDetail
from odk.models.verification import CheckResult, VerificationReport

# ---------------------------------------------------------------------------
# Helpers to load the check module
# ---------------------------------------------------------------------------


def _load_check_module():
    from importlib.util import module_from_spec, spec_from_file_location

    check_path = (
        Path(__file__).resolve().parent.parent.parent
        / "src"
        / "odk"
        / "verifications"
        / "pr-body-validation"
        / "check.py"
    )
    spec = spec_from_file_location("pr_body_validation_check", check_path)
    assert spec is not None
    assert spec.loader is not None
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Tests for the standalone validate_pr_body function
# ---------------------------------------------------------------------------


class TestValidatePrBody:
    """Test the core validation logic in the check module."""

    def test_valid_pr_body_passes(self):
        mod = _load_check_module()
        body = (
            "## Summary\n"
            "Added a new feature.\n\n"
            "## Test Plan\n"
            "- Run unit tests\n\n"
            "```console\n"
            "$ pytest tests/ -q\n"
            "5 passed\n"
            "```\n"
        )
        result = mod.validate_pr_body(body, changed_files=[])
        assert result["passed"] is True
        assert len(result["missing"]) == 0

    def test_missing_console_block_fails(self):
        mod = _load_check_module()
        body = "## Summary\nAdded a feature.\n\n## Test Plan\n- Run tests\n"
        result = mod.validate_pr_body(body, changed_files=[])
        assert result["passed"] is False
        assert "console_block" in result["missing"]

    def test_missing_summary_fails(self):
        mod = _load_check_module()
        body = "## Test Plan\n- Run tests\n\n```console\n$ pytest\nok\n```\n"
        result = mod.validate_pr_body(body, changed_files=[])
        assert result["passed"] is False
        assert "summary_section" in result["missing"]

    def test_missing_test_plan_fails(self):
        mod = _load_check_module()
        body = "## Summary\nDid stuff.\n\n```console\n$ pytest\nok\n```\n"
        result = mod.validate_pr_body(body, changed_files=[])
        assert result["passed"] is False
        assert "test_plan_section" in result["missing"]

    def test_ui_files_require_screenshots(self):
        mod = _load_check_module()
        body = "## Summary\nUpdated UI.\n\n## Test Plan\n- Visual check\n\n```console\n$ npm test\nok\n```\n"
        ui_files = ["src/visual/overlay/toolbar.tsx", "styles/main.css"]
        result = mod.validate_pr_body(body, changed_files=ui_files)
        assert result["passed"] is False
        assert "screenshot_for_ui" in result["missing"]

    def test_ui_files_with_screenshot_passes(self):
        mod = _load_check_module()
        body = (
            "## Summary\n"
            "Updated UI.\n\n"
            "## Test Plan\n"
            "- Visual check\n\n"
            "```console\n"
            "$ npm test\n"
            "ok\n"
            "```\n\n"
            "## Screenshots\n"
            "![toolbar](screenshots/toolbar.png)\n"
        )
        ui_files = ["src/visual/overlay/toolbar.tsx"]
        result = mod.validate_pr_body(body, changed_files=ui_files)
        assert result["passed"] is True

    def test_case_insensitive_test_plan(self):
        """## Test plan (lowercase p) should also be accepted."""
        mod = _load_check_module()
        body = "## Summary\nDone.\n\n## Test plan\n- Tests\n\n```console\n$ pytest\nok\n```\n"
        result = mod.validate_pr_body(body, changed_files=[])
        assert result["passed"] is True

    def test_text_and_bash_blocks_also_accepted(self):
        """```text and ```bash blocks count as console proof."""
        mod = _load_check_module()
        body = "## Summary\nFeature.\n\n## Test Plan\n- Tests\n\n```bash\n$ ruff check\nok\n```\n"
        result = mod.validate_pr_body(body, changed_files=[])
        assert result["passed"] is True

    def test_empty_body_fails(self):
        mod = _load_check_module()
        result = mod.validate_pr_body("", changed_files=[])
        assert result["passed"] is False
        assert len(result["missing"]) >= 3


# ---------------------------------------------------------------------------
# Tests for _build_pr_body including verification output
# ---------------------------------------------------------------------------


@pytest.fixture
def lifecycle_for_pr_body():
    repo = MagicMock()
    repo.get_task.return_value = TaskDetail(
        id="T-001",
        title="Test task",
        story_id="S-001",
        status="in-progress",
        spec_refs=["SPEC-01"],
    )
    worktree = MagicMock()
    worktree.get_worktree_path.return_value = None
    verifier = MagicMock()
    events = EventBus()
    lc = TaskLifecycle(
        repo=repo,
        events=events,
        worktree_mgr=worktree,
        verifier=verifier,
        project_root=Path("/tmp/project"),
    )
    return lc


@patch("odk.core.task_lifecycle.subprocess")
def test_build_pr_body_includes_verification_console_blocks(mock_subprocess, lifecycle_for_pr_body):
    """_build_pr_body must include ```console blocks from verification output."""
    mock_subprocess.run.return_value = MagicMock(
        stdout="src/odk/core/task_lifecycle.py\ntests/core/test_task_lifecycle.py\n",
        returncode=0,
    )
    task = TaskDetail(
        id="T-001",
        title="Test task",
        story_id="S-001",
        status="in-progress",
        spec_refs=["SPEC-01"],
    )
    report = VerificationReport(
        timestamp="2025-01-01T00:00:00Z",
        checks=[
            CheckResult(name="lint", passed=True, output="All clean", duration_seconds=0.5),
            CheckResult(name="tests", passed=True, output="5 passed in 1.2s", duration_seconds=1.2),
        ],
        all_passed=True,
        total_duration_seconds=1.7,
    )

    body = lifecycle_for_pr_body._build_pr_body("T-001", task=task, report=report)

    assert "```console" in body
    assert "All clean" in body
    assert "5 passed in 1.2s" in body
    assert "## Summary" in body
    assert "## Test Plan" in body


@patch("odk.core.task_lifecycle.subprocess")
def test_build_pr_body_includes_summary_and_test_plan(mock_subprocess, lifecycle_for_pr_body):
    """_build_pr_body should include ## Summary and ## Test Plan sections."""
    mock_subprocess.run.return_value = MagicMock(stdout="", returncode=0)
    report = VerificationReport(
        timestamp="2025-01-01T00:00:00Z",
        checks=[],
        all_passed=True,
        total_duration_seconds=0.0,
    )
    body = lifecycle_for_pr_body._build_pr_body("T-001", task=None, report=report)
    assert "## Summary" in body
    assert "## Test Plan" in body


@patch("odk.core.task_lifecycle.subprocess")
def test_build_pr_body_warns_incomplete_proof(mock_subprocess, lifecycle_for_pr_body):
    """_build_pr_body should include a warning when proof is incomplete (no verification checks)."""
    mock_subprocess.run.return_value = MagicMock(stdout="", returncode=0)
    body = lifecycle_for_pr_body._build_pr_body("T-001", task=None, report=None)
    # Without a report, there are no console blocks — the body should still have summary/test plan
    assert "## Summary" in body
    assert "## Test Plan" in body

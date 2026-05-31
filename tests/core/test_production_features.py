"""Tests for all ODK production-readiness features (Items 1-11).

Covers: PR body with console outputs, session ID tracking, git diff in spec-alignment,
code review with both perspectives, screenshots in PR, retrospective with LLM,
GitHub templates from odk init, pre-push verified flag, coverage with factory,
YAML output format.
"""

from __future__ import annotations

import json
import sys
import time
import types
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from odk.core.events import EventBus
from odk.core.task_lifecycle import TaskLifecycle
from odk.models.pm import TaskDetail
from odk.models.verification import CheckResult, VerificationReport

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock()
    repo.get_task.return_value = TaskDetail(
        id="T-001",
        title="Implement order validation",
        story_id="S-001",
        spec_refs=["orders.md#entities", "orders.md#error-scenarios"],
        status="open",
    )
    repo.check_dependencies.return_value = []
    repo.create_task.return_value = TaskDetail(
        id="T-002",
        title="Discovered",
        number=2,
    )
    return repo


@pytest.fixture
def mock_worktree() -> MagicMock:
    wt = MagicMock()
    wt.create.return_value = Path("/tmp/worktree/T-001")
    wt.get_worktree_path.return_value = None
    return wt


@pytest.fixture
def mock_verifier() -> MagicMock:
    v = MagicMock()
    return v


@pytest.fixture
def lifecycle(mock_repo: MagicMock, mock_worktree: MagicMock, mock_verifier: MagicMock) -> TaskLifecycle:
    events = EventBus()
    return TaskLifecycle(
        repo=mock_repo,
        events=events,
        worktree_mgr=mock_worktree,
        verifier=mock_verifier,
        project_root=Path("/tmp/project"),
    )


@pytest.fixture
def passing_report() -> VerificationReport:
    return VerificationReport(
        timestamp="2025-01-01T00:00:00Z",
        checks=[
            CheckResult(
                name="lint-ruff",
                passed=True,
                output="$ ruff check src/ tests/\nAll checks passed!",
                duration_seconds=0.1,
            ),
            CheckResult(
                name="tests-pytest",
                passed=True,
                output="$ pytest tests/ -v --tb=short\n11 passed in 0.8s",
                duration_seconds=2.0,
            ),
        ],
        all_passed=True,
        total_duration_seconds=2.1,
    )


# ---------------------------------------------------------------------------
# Item 1: PR body includes console output blocks
# ---------------------------------------------------------------------------


class TestPRBodyWithProof:
    """Item 1: PR creation with full proof including command outputs."""

    @patch("odk.core.task_lifecycle.subprocess")
    def test_pr_body_includes_verification_outputs(
        self,
        mock_subprocess: MagicMock,
        lifecycle: TaskLifecycle,
        mock_verifier: MagicMock,
        mock_worktree: MagicMock,
        mock_repo: MagicMock,
        passing_report: VerificationReport,
    ) -> None:
        """PR body should contain console code blocks with actual check outputs."""
        mock_verifier.run_all = AsyncMock(return_value=passing_report)
        mock_verifier.save_proof.return_value = Path("/tmp/proof.json")
        mock_worktree.get_worktree_path.return_value = None

        # Mock subprocess for git diff --name-only
        mock_subprocess.run.return_value = MagicMock(
            stdout="src/validation.py\nsrc/models.py\n",
            returncode=0,
        )

        # Call _build_pr_body directly
        task = mock_repo.get_task("T-001")
        body = lifecycle._build_pr_body("T-001", task=task, report=passing_report)

        assert "## Summary" in body
        assert "Implement order validation" in body
        assert "**Story**: S-001" in body
        assert "**Spec refs**: orders.md#entities, orders.md#error-scenarios" in body
        assert "## Verification Proof" in body
        assert "```console" in body
        assert "All checks passed!" in body
        assert "11 passed in 0.8s" in body
        assert "Closes #T-001" in body

    @patch("odk.core.task_lifecycle.subprocess")
    def test_pr_body_includes_files_changed(
        self,
        mock_subprocess: MagicMock,
        lifecycle: TaskLifecycle,
        passing_report: VerificationReport,
        mock_repo: MagicMock,
    ) -> None:
        """PR body should list changed files."""
        mock_subprocess.run.return_value = MagicMock(
            stdout="src/foo.py\ntests/test_foo.py\n",
            returncode=0,
        )
        task = mock_repo.get_task("T-001")
        body = lifecycle._build_pr_body("T-001", task=task, report=passing_report)

        assert "## Files Changed" in body
        assert "`src/foo.py`" in body
        assert "`tests/test_foo.py`" in body


# ---------------------------------------------------------------------------
# Item 2: Session ID tracking
# ---------------------------------------------------------------------------


class TestSessionID:
    """Item 2: Session ID stored in task metadata."""

    def test_start_stores_session_id(
        self,
        lifecycle: TaskLifecycle,
        mock_repo: MagicMock,
    ) -> None:
        """start() with session_id posts it as a comment."""
        result = lifecycle.start("T-001", session_id="sess-abc123")

        assert result["session_id"] == "sess-abc123"
        # Should have posted session comment
        calls = mock_repo.add_comment.call_args_list
        session_calls = [c for c in calls if "Session: sess-abc123" in c[0][1]]
        assert len(session_calls) == 1

    def test_start_without_session_id(
        self,
        lifecycle: TaskLifecycle,
        mock_repo: MagicMock,
    ) -> None:
        """start() without session_id does not post session comment."""
        result = lifecycle.start("T-001")

        assert result["session_id"] is None
        # add_comment should not have been called for session
        if mock_repo.add_comment.call_count > 0:
            for call in mock_repo.add_comment.call_args_list:
                assert "Session:" not in call[0][1]

    def test_session_id_in_task_detail_model(self) -> None:
        """TaskDetail model should accept session_id field."""
        task = TaskDetail(
            id="T-001",
            title="Test",
            session_id="sess-xyz",
        )
        assert task.session_id == "sess-xyz"

    def test_session_id_defaults_to_none(self) -> None:
        """TaskDetail.session_id should default to None."""
        task = TaskDetail(id="T-001", title="Test")
        assert task.session_id is None


# ---------------------------------------------------------------------------
# Item 3: Orchestrator calls odk task from project root
# ---------------------------------------------------------------------------


class TestOrchestratorProjectRoot:
    """Item 3: odk task commands work from project root."""

    def test_lifecycle_uses_project_root(self, lifecycle: TaskLifecycle) -> None:
        """TaskLifecycle stores and uses project_root."""
        assert lifecycle._root == Path("/tmp/project")

    def test_progress_works_from_root(
        self,
        lifecycle: TaskLifecycle,
        mock_repo: MagicMock,
    ) -> None:
        """progress() posts via the repo, not filesystem, so root doesn't matter."""
        lifecycle.progress("T-002", "halfway there")
        mock_repo.add_comment.assert_called_once_with("T-002", "halfway there")


# ---------------------------------------------------------------------------
# Item 4: Spec alignment receives git diff
# ---------------------------------------------------------------------------

SPEC_ALIGNMENT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "src" / "odk" / "verifications" / "spec-alignment" / "check.py"
)


def _load_check_module(path: Path, name: str) -> types.ModuleType:
    """Import a check.py as a module for direct testing."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestSpecAlignmentGitDiff:
    """Item 4: Spec alignment uses git diff instead of full files."""

    def test_get_git_diff_function_exists(self) -> None:
        """The spec-alignment module should have a _get_git_diff function."""
        mod = _load_check_module(SPEC_ALIGNMENT_PATH, "spec_alignment_check")
        assert hasattr(mod, "_get_git_diff")

    def test_system_prompt_mentions_diff(self) -> None:
        """The system prompt should reference git diff review."""
        mod = _load_check_module(SPEC_ALIGNMENT_PATH, "spec_alignment_check")
        assert "DIFF" in mod.SYSTEM_PROMPT
        assert "changes" in mod.SYSTEM_PROMPT.lower()

    @patch("subprocess.run")
    def test_get_git_diff_calls_git(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """_get_git_diff should call git diff main."""
        mod = _load_check_module(SPEC_ALIGNMENT_PATH, "spec_alignment_check")
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="diff --git a/src/main.py b/src/main.py\n+line added\n",
        )
        result = mod._get_git_diff(tmp_path, ["src/main.py"])
        assert "diff --git" in result


# ---------------------------------------------------------------------------
# Item 5: AI code review includes spec compliance and standard review
# ---------------------------------------------------------------------------

AI_CODE_REVIEW_PATH = (
    Path(__file__).resolve().parent.parent.parent / "src" / "odk" / "verifications" / "ai-code-review" / "check.py"
)


class TestAICodeReviewBothPerspectives:
    """Item 5: AI code review covers spec compliance AND standard review."""

    def test_system_prompt_covers_spec_compliance(self) -> None:
        """System prompt should mention spec compliance perspective."""
        mod = _load_check_module(AI_CODE_REVIEW_PATH, "ai_code_review_check")
        prompt = mod.SYSTEM_PROMPT
        assert "Spec Compliance" in prompt
        assert "interface contracts" in prompt.lower() or "interface" in prompt.lower()

    def test_system_prompt_covers_standard_review(self) -> None:
        """System prompt should mention DRY, YAGNI, SOLID, Security."""
        mod = _load_check_module(AI_CODE_REVIEW_PATH, "ai_code_review_check")
        prompt = mod.SYSTEM_PROMPT
        assert "DRY" in prompt
        assert "YAGNI" in prompt
        assert "SOLID" in prompt
        assert "Security" in prompt or "security" in prompt.lower()

    def test_system_prompt_has_severity_levels(self) -> None:
        """System prompt should define critical, warning, info severities."""
        mod = _load_check_module(AI_CODE_REVIEW_PATH, "ai_code_review_check")
        prompt = mod.SYSTEM_PROMPT
        assert "critical" in prompt
        assert "warning" in prompt
        assert "info" in prompt

    def test_review_uses_git_diff(self) -> None:
        """The ai-code-review module should have a _get_git_diff function."""
        mod = _load_check_module(AI_CODE_REVIEW_PATH, "ai_code_review_check")
        assert hasattr(mod, "_get_git_diff")

    def test_categories_include_spec_and_standard(self) -> None:
        """The review should support both spec and standard review categories."""
        mod = _load_check_module(AI_CODE_REVIEW_PATH, "ai_code_review_check")
        prompt = mod.SYSTEM_PROMPT
        assert "spec_compliance" in prompt
        assert "dry" in prompt
        assert "security" in prompt


# ---------------------------------------------------------------------------
# Item 6: Screenshots included in PR body when they exist
# ---------------------------------------------------------------------------


class TestScreenshotCapture:
    """Item 6: Screenshots in PR body."""

    def test_no_screenshots_no_section(
        self,
        lifecycle: TaskLifecycle,
    ) -> None:
        """When no screenshots exist, PR body should not have Screenshots section."""
        lines = lifecycle._collect_screenshots("T-001")
        assert lines == []

    def test_screenshots_collected(
        self,
        lifecycle: TaskLifecycle,
        tmp_path: Path,
    ) -> None:
        """When screenshots exist, they are included as image links."""
        # Override project root
        lifecycle._root = tmp_path
        screenshots_dir = tmp_path / ".odk" / "proofs" / "T-001" / "screenshots"
        screenshots_dir.mkdir(parents=True)
        (screenshots_dir / "dashboard.png").write_text("fake-png")
        (screenshots_dir / "order-form.jpg").write_text("fake-jpg")

        lines = lifecycle._collect_screenshots("T-001")

        assert len(lines) == 2
        assert "![dashboard]" in lines[0]
        assert "![order form]" in lines[1]
        assert ".png" in lines[0]
        assert ".jpg" in lines[1]

    @patch("odk.core.task_lifecycle.subprocess")
    def test_screenshots_in_pr_body(
        self,
        mock_subprocess: MagicMock,
        lifecycle: TaskLifecycle,
        passing_report: VerificationReport,
        mock_repo: MagicMock,
        tmp_path: Path,
    ) -> None:
        """PR body should contain ## Screenshots section when screenshots exist."""
        lifecycle._root = tmp_path
        screenshots_dir = tmp_path / ".odk" / "proofs" / "T-001" / "screenshots"
        screenshots_dir.mkdir(parents=True)
        (screenshots_dir / "screen.png").write_text("fake")

        mock_subprocess.run.return_value = MagicMock(stdout="", returncode=0)

        task = mock_repo.get_task("T-001")
        body = lifecycle._build_pr_body("T-001", task=task, report=passing_report)

        assert "## Screenshots" in body
        assert "![screen]" in body


# ---------------------------------------------------------------------------
# Item 7: Memory retrospective calls LLM
# ---------------------------------------------------------------------------


class TestRetrospectiveLLM:
    """Item 7: Memory retrospective with real LLM implementation."""

    def test_run_llm_retrospective_returns_none_without_strands(self) -> None:
        """_run_llm_retrospective gracefully returns None when strands not available."""
        from odk.cli.memory_cmd import _run_llm_retrospective

        original_import = __import__

        def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name in ("strands", "strands.models.bedrock"):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            tasks = [MagicMock(id="T-001", title="Task 1")]
            result = _run_llm_retrospective(tasks, None)
        assert result is None

    def test_retrospective_produces_proposals_with_mock_llm(self) -> None:
        """_run_llm_retrospective returns structured proposals with mocked LLM."""
        from odk.cli.memory_cmd import _run_llm_retrospective

        ai_response = json.dumps(
            {
                "patterns": ["Tasks took longer than estimated"],
                "templates": ["Add estimation field to task template"],
                "rules": ["Always write tests before implementation"],
                "summary": "Good sprint overall.",
            }
        )

        mock_agent_instance = MagicMock()
        mock_agent_instance.return_value = ai_response
        mock_agent_cls = MagicMock(return_value=mock_agent_instance)
        mock_bedrock_cls = MagicMock()
        mock_boto3 = MagicMock()

        mock_strands_mod = types.ModuleType("strands")
        mock_strands_mod.Agent = mock_agent_cls
        mock_bedrock_mod = types.ModuleType("strands.models.bedrock")
        mock_bedrock_mod.BedrockModel = mock_bedrock_cls

        with patch.dict(
            sys.modules,
            {
                "strands": mock_strands_mod,
                "strands.models": types.ModuleType("strands.models"),
                "strands.models.bedrock": mock_bedrock_mod,
                "boto3": mock_boto3,
            },
        ):
            tasks = [MagicMock(id="T-001", title="Task 1")]
            result = _run_llm_retrospective(tasks, "sprint-1")

        assert result is not None
        assert "patterns" in result
        assert "templates" in result
        assert "rules" in result


# ---------------------------------------------------------------------------
# Item 8: Git templates created by odk init
# ---------------------------------------------------------------------------


class TestGitTemplatesInit:
    """Item 8: odk init creates .github/ templates."""

    def test_init_creates_github_templates(self, tmp_path: Path, monkeypatch: object) -> None:
        """odk init should create .github/ISSUE_TEMPLATE/ and PR template."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        from typer.testing import CliRunner

        from odk.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["init", "--name", "testproj"])

        assert result.exit_code == 0

        # Check issue templates
        assert (tmp_path / ".github" / "ISSUE_TEMPLATE" / "task.md").is_file()
        assert (tmp_path / ".github" / "ISSUE_TEMPLATE" / "story.md").is_file()
        assert (tmp_path / ".github" / "ISSUE_TEMPLATE" / "epic.md").is_file()

        # Check PR template
        assert (tmp_path / ".github" / "PULL_REQUEST_TEMPLATE.md").is_file()

    def test_task_template_content(self, tmp_path: Path, monkeypatch: object) -> None:
        """Task template should contain expected fields."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        from typer.testing import CliRunner

        from odk.cli import app

        runner = CliRunner()
        runner.invoke(app, ["init", "--name", "testproj"])

        content = (tmp_path / ".github" / "ISSUE_TEMPLATE" / "task.md").read_text()
        assert "Story" in content
        assert "Spec refs" in content
        assert "Dependencies" in content
        assert "Acceptance Criteria" in content
        assert "Test Strategy" in content

    def test_pr_template_content(self, tmp_path: Path, monkeypatch: object) -> None:
        """PR template should have verification proof placeholder."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        from typer.testing import CliRunner

        from odk.cli import app

        runner = CliRunner()
        runner.invoke(app, ["init", "--name", "testproj"])

        content = (tmp_path / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text()
        assert "Verification Proof" in content
        assert "Closes #" in content


# ---------------------------------------------------------------------------
# Item 9: Pre-push hook checks verified flag
# ---------------------------------------------------------------------------


class TestPrePushVerifiedFlag:
    """Item 9: Pre-push hook respects .odk/.verified flag."""

    @patch("odk.core.task_lifecycle.subprocess")
    def test_done_writes_verified_flag(
        self,
        mock_subprocess: MagicMock,
        mock_repo: MagicMock,
        mock_worktree: MagicMock,
        mock_verifier: MagicMock,
        tmp_path: Path,
    ) -> None:
        """done() should write .odk/.verified before pushing."""
        events = EventBus()
        lc = TaskLifecycle(
            repo=mock_repo,
            events=events,
            worktree_mgr=mock_worktree,
            verifier=mock_verifier,
            project_root=tmp_path,
        )

        report = VerificationReport(
            timestamp="2025-01-01T00:00:00Z",
            checks=[CheckResult(name="lint", passed=True, output="ok", duration_seconds=0.1)],
            all_passed=True,
            total_duration_seconds=0.1,
        )
        mock_verifier.run_all = AsyncMock(return_value=report)
        mock_verifier.save_proof.return_value = tmp_path / "proof.json"
        mock_worktree.get_worktree_path.return_value = None
        mock_subprocess.run.return_value = MagicMock(stdout="", returncode=0)

        lc.done("T-001")

        flag = tmp_path / ".odk" / ".verified"
        assert flag.is_file()
        ts = float(flag.read_text())
        assert abs(time.time() - ts) < 10  # Written within last 10 seconds

    def test_pre_push_hook_has_verified_check(self, tmp_path: Path, monkeypatch: object) -> None:
        """Pre-push hook script should check for .odk/.verified flag."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        from typer.testing import CliRunner

        from odk.cli import app

        runner = CliRunner()
        runner.invoke(app, ["init", "--name", "testproj"])

        pre_push = tmp_path / ".odk" / "hooks" / "pre-push"
        assert pre_push.is_file()
        content = pre_push.read_text()
        assert ".odk/.verified" in content
        assert "skipping verification" in content.lower() or "skip" in content.lower()

    def test_write_verified_flag(self, tmp_path: Path) -> None:
        """_write_verified_flag creates a timestamp file."""
        events = EventBus()
        lc = TaskLifecycle(
            repo=MagicMock(),
            events=events,
            worktree_mgr=MagicMock(),
            verifier=MagicMock(),
            project_root=tmp_path,
        )

        lc._write_verified_flag()

        flag = tmp_path / ".odk" / ".verified"
        assert flag.is_file()
        ts = float(flag.read_text())
        assert ts > 0


# ---------------------------------------------------------------------------
# Item 10: Coverage works with repository factory
# ---------------------------------------------------------------------------


class TestCoverageFactory:
    """Item 10: Coverage command uses repository factory."""

    def test_coverage_with_local_backend(self, tmp_path: Path, monkeypatch: object) -> None:
        """Coverage command should work with local backend."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        from typer.testing import CliRunner

        from odk.cli import app

        # Create minimal config
        odk_dir = tmp_path / ".odk"
        odk_dir.mkdir()
        (odk_dir / "config.yaml").write_text(
            "project:\n  name: test\n  remote: local\n"
            "  spec_location: docs/specs\n  adrs_location: docs/adrs\n"
            "  research_location: docs/research\n"
        )
        (odk_dir / "manifest.yaml").write_text("{}")

        # Create a spec file
        spec_dir = tmp_path / "docs" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "api.md").write_text("# API Spec")

        runner = CliRunner()
        result = runner.invoke(app, ["task", "coverage"])
        assert result.exit_code == 0
        assert "Coverage:" in result.output


# ---------------------------------------------------------------------------
# Item 11: YAML output format
# ---------------------------------------------------------------------------


class TestYAMLOutput:
    """Item 11: YAML output format for all list/status commands."""

    def test_yaml_task_list(self, tmp_path: Path, monkeypatch: object) -> None:
        """--format yaml task list should produce valid YAML."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        from typer.testing import CliRunner

        from odk.cli import app

        odk_dir = tmp_path / ".odk"
        odk_dir.mkdir()
        (odk_dir / "config.yaml").write_text(
            "project:\n  name: test\n  remote: local\n"
            "  spec_location: docs/specs\n  adrs_location: docs/adrs\n"
            "  research_location: docs/research\n"
        )
        manifest_data = {
            "tasks": {
                "T-001": {"title": "Test task", "story": None, "status": "open", "dependencies": []},
            },
            "stories": {},
            "epics": {},
        }
        (odk_dir / "manifest.yaml").write_text(yaml.dump(manifest_data))

        runner = CliRunner()
        result = runner.invoke(app, ["--format", "yaml", "task", "list"])
        assert result.exit_code == 0
        parsed = yaml.safe_load(result.output)
        assert isinstance(parsed, list)
        assert parsed[0]["id"] == "T-001"

    def test_yaml_formatter_produces_valid_yaml(self) -> None:
        """YamlFormatter.format should produce parseable YAML."""
        from odk.output.formatters import YamlFormatter

        formatter = YamlFormatter()
        data = [{"id": "T-001", "title": "Test", "status": "open"}]
        output = formatter.format(data)
        parsed = yaml.safe_load(output)
        assert parsed == data

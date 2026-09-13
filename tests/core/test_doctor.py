"""Tests for ydk doctor health checks."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from ydk.core.doctor import CheckResult, CheckSeverity, Doctor

if TYPE_CHECKING:
    from pathlib import Path


class TestCheckPython:
    def test_passes_on_current_python(self) -> None:
        doc = Doctor()
        result = doc._check_python()
        assert result.severity == CheckSeverity.ok
        assert result.name == "Python"
        assert "3.13" in result.message or "3.14" in result.message


class TestCheckGit:
    def test_passes_when_git_installed(self) -> None:
        doc = Doctor()
        result = doc._check_git()
        assert result.severity == CheckSeverity.ok
        assert result.name == "Git"


class TestCheckGitRepo:
    def test_passes_in_git_repo(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        doc = Doctor(project_root=tmp_path)
        result = doc._check_git_repo()
        assert result.severity == CheckSeverity.ok
        assert result.name == "Git repo"

    def test_fails_outside_git_repo(self, tmp_path: Path) -> None:
        doc = Doctor(project_root=tmp_path)
        result = doc._check_git_repo()
        assert result.severity == CheckSeverity.error
        assert result.name == "Git repo"


class TestCheckYdkConfig:
    def test_passes_with_valid_config(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".ydk"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("project:\n  name: test-project\n")
        doc = Doctor(project_root=tmp_path)
        result = doc._check_ydk_config()
        assert result.severity == CheckSeverity.ok
        assert result.name == "YDK config"

    def test_fails_when_missing(self, tmp_path: Path) -> None:
        doc = Doctor(project_root=tmp_path)
        result = doc._check_ydk_config()
        assert result.severity == CheckSeverity.error
        assert result.name == "YDK config"

    def test_fails_with_invalid_yaml(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".ydk"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("project:\n  name: 123\n  bogus_field: nope\n")
        doc = Doctor(project_root=tmp_path)
        result = doc._check_ydk_config()
        assert result.severity == CheckSeverity.error
        assert result.name == "YDK config"


class TestCheckSpecLocation:
    def test_passes_when_directory_exists(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".ydk"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("project:\n  name: test\n  spec_location: docs/specs\n")
        (tmp_path / "docs" / "specs").mkdir(parents=True)
        doc = Doctor(project_root=tmp_path)
        result = doc._check_spec_location()
        assert result.severity == CheckSeverity.ok
        assert result.name == "Spec location"

    def test_warns_when_directory_missing(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".ydk"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("project:\n  name: test\n  spec_location: docs/specs\n")
        doc = Doctor(project_root=tmp_path)
        result = doc._check_spec_location()
        assert result.severity == CheckSeverity.warning
        assert result.name == "Spec location"


class TestCheckAdrsLocation:
    def test_passes_when_directory_exists(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".ydk"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("project:\n  name: test\n")
        (tmp_path / "docs" / "adrs").mkdir(parents=True)
        doc = Doctor(project_root=tmp_path)
        result = doc._check_adrs_location()
        assert result.severity == CheckSeverity.ok

    def test_warns_when_directory_missing(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".ydk"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("project:\n  name: test\n")
        doc = Doctor(project_root=tmp_path)
        result = doc._check_adrs_location()
        assert result.severity == CheckSeverity.warning


class TestCheckProjectRules:
    def test_passes_when_file_exists(self, tmp_path: Path) -> None:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "project-rules.md").write_text("# Rules\n")
        doc = Doctor(project_root=tmp_path)
        result = doc._check_project_rules()
        assert result.severity == CheckSeverity.ok
        assert result.name == "Project rules"

    def test_warns_when_file_missing(self, tmp_path: Path) -> None:
        doc = Doctor(project_root=tmp_path)
        result = doc._check_project_rules()
        assert result.severity == CheckSeverity.warning
        assert result.name == "Project rules"


class TestCheckJinja2:
    def test_passes_when_installed(self) -> None:
        doc = Doctor()
        result = doc._check_jinja2()
        assert result.severity == CheckSeverity.ok
        assert result.name == "Jinja2"


class TestCheckTestRunner:
    def test_passes_when_pytest_available(self) -> None:
        doc = Doctor()
        result = doc._check_test_runner()
        # pytest is available in this environment
        assert result.severity == CheckSeverity.ok
        assert result.name == "Test runner"


class TestCheckLinter:
    def test_passes_when_ruff_available(self) -> None:
        doc = Doctor()
        result = doc._check_linter()
        assert result.severity == CheckSeverity.ok
        assert result.name == "Linter"


class TestCheckTypeChecker:
    def test_passes_when_available(self) -> None:
        doc = Doctor()
        result = doc._check_type_checker()
        # ty or mypy should be available
        assert result.severity in (CheckSeverity.ok, CheckSeverity.warning)
        assert result.name == "Type checker"


class TestCheckRemoteCli:
    def test_returns_check_result(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".ydk"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("project:\n  name: test\n  remote: github\n")
        doc = Doctor(project_root=tmp_path)
        result = doc._check_remote_cli()
        assert isinstance(result, CheckResult)
        assert result.name == "Remote CLI"


class TestRunAll:
    def test_returns_results_for_all_checks(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        config_dir = tmp_path / ".ydk"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("project:\n  name: test\n")
        doc = Doctor(project_root=tmp_path)
        results = doc.run_all()
        assert len(results) == 13
        assert all(isinstance(r, CheckResult) for r in results)


def _summary(task_id: str, status: str) -> object:
    from ydk.models.pm import TaskSummary

    return TaskSummary(id=task_id, title=f"Title {task_id}", status=status)


class TestCheckTaskPrDrift:
    def test_gh_absent_returns_ok_and_skips(self) -> None:
        doc = Doctor()
        with patch("shutil.which", return_value=None):
            result = doc._check_task_pr_drift()
        assert result.severity == CheckSeverity.ok
        assert result.name == "Task/PR drift"
        assert "skipped" in result.message.lower()

    def test_gh_present_no_candidates_returns_ok(self) -> None:
        doc = Doctor()
        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = [_summary("T-001", "done")]
        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("ydk.repositories.factory.get_task_repository", return_value=mock_repo),
        ):
            result = doc._check_task_pr_drift()
        assert result.severity == CheckSeverity.ok
        assert "no task/pr status drift" in result.message.lower()

    def test_gh_present_merged_pr_reports_warning_with_detail(self) -> None:
        doc = Doctor()
        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = [_summary("T-002", "in-review")]
        pr = {"number": 7, "state": "MERGED", "createdAt": "2026-01-01T00:00:00Z"}
        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("ydk.repositories.factory.get_task_repository", return_value=mock_repo),
            patch("ydk.core.task_pr_lookup.list_prs", return_value=[pr]),
            patch("ydk.core.task_pr_lookup.find_task_pr", return_value=pr),
        ):
            result = doc._check_task_pr_drift()
        assert result.severity == CheckSeverity.warning
        assert "1" in result.message
        assert result.detail is not None
        assert "ydk task close T-002" in result.detail

    def test_gh_present_open_or_no_pr_returns_ok(self) -> None:
        doc = Doctor()
        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = [_summary("T-003", "open")]
        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("ydk.repositories.factory.get_task_repository", return_value=mock_repo),
            patch("ydk.core.task_pr_lookup.list_prs", return_value=[]),
            patch("ydk.core.task_pr_lookup.find_task_pr", return_value=None),
        ):
            result = doc._check_task_pr_drift()
        assert result.severity == CheckSeverity.ok

    def test_repository_error_returns_warning_and_does_not_propagate(self) -> None:
        doc = Doctor()
        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("ydk.repositories.factory.get_task_repository", side_effect=RuntimeError("boom")),
        ):
            results = doc.run_all()
        drift_result = next(r for r in results if r.name == "Task/PR drift")
        assert drift_result.severity == CheckSeverity.warning
        assert "could not check" in drift_result.message.lower()


class TestHasErrors:
    def test_returns_true_when_error_exists(self) -> None:
        doc = Doctor()
        results = [
            CheckResult("a", CheckSeverity.ok, "good"),
            CheckResult("b", CheckSeverity.error, "bad"),
        ]
        assert doc.has_errors(results) is True

    def test_returns_false_when_only_warnings(self) -> None:
        doc = Doctor()
        results = [
            CheckResult("a", CheckSeverity.ok, "good"),
            CheckResult("b", CheckSeverity.warning, "meh"),
        ]
        assert doc.has_errors(results) is False


class TestHasWarnings:
    def test_returns_true_when_warning_exists(self) -> None:
        doc = Doctor()
        results = [
            CheckResult("a", CheckSeverity.ok, "good"),
            CheckResult("b", CheckSeverity.warning, "meh"),
        ]
        assert doc.has_warnings(results) is True

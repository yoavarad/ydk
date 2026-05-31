"""Tests for odk doctor health checks."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from odk.core.doctor import CheckResult, CheckSeverity, Doctor

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


class TestCheckOdkConfig:
    def test_passes_with_valid_config(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".odk"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("project:\n  name: test-project\n")
        doc = Doctor(project_root=tmp_path)
        result = doc._check_odk_config()
        assert result.severity == CheckSeverity.ok
        assert result.name == "ODK config"

    def test_fails_when_missing(self, tmp_path: Path) -> None:
        doc = Doctor(project_root=tmp_path)
        result = doc._check_odk_config()
        assert result.severity == CheckSeverity.error
        assert result.name == "ODK config"

    def test_fails_with_invalid_yaml(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".odk"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("project:\n  name: 123\n  bogus_field: nope\n")
        doc = Doctor(project_root=tmp_path)
        result = doc._check_odk_config()
        assert result.severity == CheckSeverity.error
        assert result.name == "ODK config"


class TestCheckSpecLocation:
    def test_passes_when_directory_exists(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".odk"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("project:\n  name: test\n  spec_location: docs/specs\n")
        (tmp_path / "docs" / "specs").mkdir(parents=True)
        doc = Doctor(project_root=tmp_path)
        result = doc._check_spec_location()
        assert result.severity == CheckSeverity.ok
        assert result.name == "Spec location"

    def test_warns_when_directory_missing(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".odk"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("project:\n  name: test\n  spec_location: docs/specs\n")
        doc = Doctor(project_root=tmp_path)
        result = doc._check_spec_location()
        assert result.severity == CheckSeverity.warning
        assert result.name == "Spec location"


class TestCheckAdrsLocation:
    def test_passes_when_directory_exists(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".odk"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("project:\n  name: test\n")
        (tmp_path / "docs" / "adrs").mkdir(parents=True)
        doc = Doctor(project_root=tmp_path)
        result = doc._check_adrs_location()
        assert result.severity == CheckSeverity.ok

    def test_warns_when_directory_missing(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".odk"
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
        config_dir = tmp_path / ".odk"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("project:\n  name: test\n  remote: github\n")
        doc = Doctor(project_root=tmp_path)
        result = doc._check_remote_cli()
        assert isinstance(result, CheckResult)
        assert result.name == "Remote CLI"


class TestRunAll:
    def test_returns_results_for_all_checks(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        config_dir = tmp_path / ".odk"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("project:\n  name: test\n")
        doc = Doctor(project_root=tmp_path)
        results = doc.run_all()
        assert len(results) == 12
        assert all(isinstance(r, CheckResult) for r in results)


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

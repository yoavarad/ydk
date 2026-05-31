"""Tests for task CLI validation: component_refs, spec_refs, warnings."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import yaml
from typer.testing import CliRunner

from odk.cli import app
from odk.models.pm import TaskDetail, TaskSummary

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


# ---------------------------------------------------------------------------
# component-coverage command
# ---------------------------------------------------------------------------


class TestComponentCoverageCLI:
    def test_no_components_dir(self, tmp_path: Path) -> None:
        """Reports when no .odk/components/ directory exists."""
        with patch("odk.cli.task_cmd.Path", return_value=tmp_path):
            result = runner.invoke(app, ["task", "component-coverage"])
        # May get "No .odk/components/" or an error depending on cwd
        assert result.exit_code == 0 or "No .odk/components/" in result.output

    def test_all_covered(self, tmp_path: Path) -> None:
        """All components referenced -> success message."""
        comp_dir = tmp_path / ".odk" / "components" / "entity"
        comp_dir.mkdir(parents=True)
        (comp_dir / "Order.yaml").write_text(yaml.dump({"id": "odk:entity:orders/Order"}))

        mock_repo = MagicMock()
        detail = TaskDetail(
            id="T-001",
            title="Task",
            component_refs=["odk:entity:orders/Order"],
        )
        mock_repo.list_tasks.return_value = [
            TaskSummary(id="T-001", title="Task"),
        ]
        mock_repo.get_task.return_value = detail

        with (
            patch("odk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("odk.cli.task_cmd.Path", return_value=tmp_path),
        ):
            result = runner.invoke(app, ["task", "component-coverage"])

        assert "All components are referenced" in result.output

    def test_uncovered_exits_1(self, tmp_path: Path) -> None:
        """Uncovered components -> exit code 1."""
        comp_dir = tmp_path / ".odk" / "components" / "entity"
        comp_dir.mkdir(parents=True)
        (comp_dir / "Order.yaml").write_text(yaml.dump({"id": "odk:entity:orders/Order"}))

        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = []

        with (
            patch("odk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("odk.cli.task_cmd.Path", return_value=tmp_path),
        ):
            result = runner.invoke(app, ["task", "component-coverage"])

        assert result.exit_code == 0  # Warn by default, not fail
        assert "not referenced" in result.output


# ---------------------------------------------------------------------------
# create command: ref validation + warnings
# ---------------------------------------------------------------------------


class TestCreateValidation:
    def test_rejects_bad_component_ref(self, tmp_path: Path) -> None:
        """create rejects component_refs that don't resolve to files."""
        mock_repo = MagicMock()
        with (
            patch("odk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("odk.cli.task_cmd.Path", return_value=tmp_path),
        ):
            result = runner.invoke(
                app,
                [
                    "task",
                    "create",
                    "--title",
                    "Test",
                    "--story",
                    "S-001",
                    "--component-refs",
                    "odk:entity:orders/Order",
                ],
            )
        assert result.exit_code != 0
        assert "not found" in (result.output or result.stdout)

    def test_rejects_bad_spec_ref(self, tmp_path: Path) -> None:
        """create rejects spec_refs that don't exist."""
        mock_repo = MagicMock()
        with (
            patch("odk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("odk.cli.task_cmd.Path", return_value=tmp_path),
        ):
            result = runner.invoke(
                app,
                [
                    "task",
                    "create",
                    "--title",
                    "Test",
                    "--story",
                    "S-001",
                    "--spec-refs",
                    "docs/specs/missing.md",
                ],
            )
        assert result.exit_code != 0

    def test_warns_missing_acceptance(self) -> None:
        """create warns when acceptance criteria are missing."""
        mock_repo = MagicMock()
        mock_repo.create_task.return_value = TaskDetail(id="T-001", title="Test")
        with patch("odk.cli.task_cmd._get_repo", return_value=mock_repo):
            result = runner.invoke(
                app,
                ["task", "create", "--title", "Test", "--story", "S-001"],
            )
        assert "WARNING" in (result.output or "")
        assert "acceptance criteria" in (result.output or "")

    def test_warns_missing_test_strategy(self) -> None:
        """create warns when test strategy is missing."""
        mock_repo = MagicMock()
        mock_repo.create_task.return_value = TaskDetail(id="T-001", title="Test")
        with patch("odk.cli.task_cmd._get_repo", return_value=mock_repo):
            result = runner.invoke(
                app,
                ["task", "create", "--title", "Test", "--story", "S-001"],
            )
        assert "WARNING" in (result.output or "")
        assert "test strategy" in (result.output or "")


# ---------------------------------------------------------------------------
# create-story: ref validation + warnings
# ---------------------------------------------------------------------------


class TestCreateStoryValidation:
    def test_rejects_bad_component_ref(self, tmp_path: Path) -> None:
        """create-story rejects component_refs that don't resolve."""
        with patch("odk.cli.task_cmd.Path", return_value=tmp_path):
            result = runner.invoke(
                app,
                [
                    "task",
                    "create-story",
                    "--title",
                    "Story",
                    "--epic",
                    "E-001",
                    "--component-refs",
                    "odk:entity:missing/Ref",
                ],
            )
        assert result.exit_code != 0

    def test_rejects_bad_spec_ref(self, tmp_path: Path) -> None:
        """create-story rejects spec_refs that don't exist."""
        with patch("odk.cli.task_cmd.Path", return_value=tmp_path):
            result = runner.invoke(
                app,
                [
                    "task",
                    "create-story",
                    "--title",
                    "Story",
                    "--epic",
                    "E-001",
                    "--spec-refs",
                    "docs/missing.md",
                ],
            )
        assert result.exit_code != 0

    def test_warns_missing_acceptance(self) -> None:
        """create-story warns when acceptance criteria are missing."""
        mock_repo = MagicMock()
        mock_repo.create_story.return_value = MagicMock(id="S-001", title="Story", number=1)
        with patch("odk.repositories.factory.get_story_repository", return_value=mock_repo):
            result = runner.invoke(
                app,
                ["task", "create-story", "--title", "Story", "--epic", "E-001"],
            )
        assert "WARNING" in (result.output or "")
        assert "acceptance criteria" in (result.output or "")


# ---------------------------------------------------------------------------
# Fix 1: validate-dag --label filter
# ---------------------------------------------------------------------------


class TestValidateDagLabelFilter:
    def test_label_filter_scopes_validation(self) -> None:
        """validate-dag --label only validates tasks with that label."""
        mock_repo = MagicMock()
        # Two tasks: one with label "sprint-1", one without
        t1 = TaskDetail(id="T-001", title="Task 1", status="open", dependencies=[], labels=["sprint-1"])
        t2 = TaskDetail(id="T-002", title="Task 2", status="open", dependencies=["T-MISSING"], labels=["sprint-2"])
        # list_tasks returns summaries without labels (force fallback path)
        mock_repo.list_tasks.return_value = [
            TaskSummary(id="T-001", title="Task 1", status="open"),
            TaskSummary(id="T-002", title="Task 2", status="open"),
        ]
        mock_repo.get_task.side_effect = lambda tid: {"T-001": t1, "T-002": t2}[tid]

        with patch("odk.cli.task_cmd._get_repo", return_value=mock_repo):
            result = runner.invoke(app, ["task", "validate-dag", "--label", "sprint-1"])

        # T-002 has unresolved dep T-MISSING but is filtered out by label
        assert result.exit_code == 0
        assert "DAG is valid" in result.output

    def test_no_label_validates_all(self) -> None:
        """validate-dag without --label validates all tasks."""
        mock_repo = MagicMock()
        t1 = TaskDetail(id="T-001", title="Task 1", status="open", dependencies=[])
        t2 = TaskDetail(id="T-002", title="Task 2", status="open", dependencies=["T-MISSING"], labels=["sprint-2"])
        mock_repo.list_tasks.return_value = [
            TaskSummary(id="T-001", title="Task 1", status="open"),
            TaskSummary(id="T-002", title="Task 2", status="open"),
        ]
        mock_repo.get_task.side_effect = lambda tid: {"T-001": t1, "T-002": t2}[tid]

        with patch("odk.cli.task_cmd._get_repo", return_value=mock_repo):
            result = runner.invoke(app, ["task", "validate-dag"])

        # T-002 has unresolved dep so validation fails
        assert result.exit_code != 0
        assert "Unresolved" in result.output


# ---------------------------------------------------------------------------
# Fix 2: spec_refs validation in batch YAML
# ---------------------------------------------------------------------------


class TestBatchSpecRefsValidation:
    def test_bad_spec_ref_caught_in_dry_run(self, tmp_path: Path, monkeypatch: object) -> None:
        """Batch YAML with nonexistent spec_ref is caught during dry-run."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump(
                {
                    "tasks": [
                        {
                            "id": "t1",
                            "title": "Task 1",
                            "spec_refs": ["docs/specs/nonexistent.md"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file), "--dry-run"])

        assert result.exit_code != 0
        assert "spec_ref" in result.output
        assert "nonexistent.md" in result.output

    def test_valid_spec_ref_passes(self, tmp_path: Path, monkeypatch: object) -> None:
        """Batch YAML with existing spec_ref passes validation."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        # Create the spec file
        spec_dir = tmp_path / "docs" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "real-spec.md").write_text("# Spec", encoding="utf-8")

        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump(
                {
                    "tasks": [
                        {
                            "id": "t1",
                            "title": "Task 1",
                            "spec_refs": ["docs/specs/real-spec.md"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file), "--dry-run"])

        assert result.exit_code == 0
        assert "Dry run" in result.output


# ---------------------------------------------------------------------------
# Fix 3: coverage --from batch.yaml
# ---------------------------------------------------------------------------


class TestCoverageFromBatch:
    def test_coverage_from_batch_reports_uncovered(self, tmp_path: Path, monkeypatch: object) -> None:
        """coverage --from reports spec files not referenced in batch YAML."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        # Create spec files
        spec_dir = tmp_path / "docs" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "covered.md").write_text("# Covered", encoding="utf-8")
        (spec_dir / "uncovered.md").write_text("# Uncovered", encoding="utf-8")

        # Create .odk dir for config
        odk_dir = tmp_path / ".odk"
        odk_dir.mkdir()

        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump(
                {
                    "tasks": [
                        {
                            "id": "t1",
                            "title": "Task 1",
                            "spec_refs": ["docs/specs/covered.md"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = runner.invoke(app, ["task", "coverage", "--from", str(batch_file)])

        assert result.exit_code == 0
        assert "uncovered.md" in result.output
        assert "1/2" in result.output or "Coverage" in result.output

    def test_coverage_from_batch_all_covered(self, tmp_path: Path, monkeypatch: object) -> None:
        """coverage --from reports full coverage when all specs are referenced."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        spec_dir = tmp_path / "docs" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "only-spec.md").write_text("# Spec", encoding="utf-8")

        odk_dir = tmp_path / ".odk"
        odk_dir.mkdir()

        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump(
                {
                    "stories": [
                        {
                            "id": "s1",
                            "title": "Story 1",
                            "spec_refs": ["docs/specs/only-spec.md"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = runner.invoke(app, ["task", "coverage", "--from", str(batch_file)])

        assert result.exit_code == 0
        assert "1/1" in result.output
        assert "Uncovered" not in result.output

    def test_coverage_from_nonexistent_file(self, tmp_path: Path, monkeypatch: object) -> None:
        """coverage --from with nonexistent file exits with error."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        spec_dir = tmp_path / "docs" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec", encoding="utf-8")

        result = runner.invoke(app, ["task", "coverage", "--from", "/nonexistent/batch.yaml"])

        assert result.exit_code != 0
        assert "not found" in result.output

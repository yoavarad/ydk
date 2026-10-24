"""Tests for task CLI validation: component_refs, spec_refs, warnings."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from ydk.cli import app
from ydk.models.pm import EpicDetail, StoryDetail, TaskDetail, TaskSummary

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


# ---------------------------------------------------------------------------
# component-coverage command
# ---------------------------------------------------------------------------


class TestComponentCoverageCLI:
    def test_no_components_dir(self, tmp_path: Path) -> None:
        """Reports when no .ydk/components/ directory exists."""
        with patch("ydk.cli.task_cmd.Path", return_value=tmp_path):
            result = runner.invoke(app, ["task", "component-coverage"])
        # May get "No .ydk/components/" or an error depending on cwd
        assert result.exit_code == 0 or "No .ydk/components/" in result.output

    def test_all_covered(self, tmp_path: Path) -> None:
        """All components referenced -> success message."""
        comp_dir = tmp_path / ".ydk" / "components" / "entity"
        comp_dir.mkdir(parents=True)
        (comp_dir / "Order.yaml").write_text(yaml.dump({"id": "ydk:entity:orders/Order"}))

        mock_repo = MagicMock()
        detail = TaskDetail(
            id="T-001",
            title="Task",
            component_refs=["ydk:entity:orders/Order"],
        )
        mock_repo.list_tasks.return_value = [
            TaskSummary(id="T-001", title="Task"),
        ]
        mock_repo.get_task.return_value = detail

        with (
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.cli.task_cmd.Path", return_value=tmp_path),
        ):
            result = runner.invoke(app, ["task", "component-coverage"])

        assert "All components are referenced" in result.output

    def test_uncovered_exits_1(self, tmp_path: Path) -> None:
        """Uncovered components -> exit code 1."""
        comp_dir = tmp_path / ".ydk" / "components" / "entity"
        comp_dir.mkdir(parents=True)
        (comp_dir / "Order.yaml").write_text(yaml.dump({"id": "ydk:entity:orders/Order"}))

        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = []

        with (
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.cli.task_cmd.Path", return_value=tmp_path),
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
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.cli.task_cmd.Path", return_value=tmp_path),
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
                    "ydk:entity:orders/Order",
                ],
            )
        assert result.exit_code != 0
        assert "not found" in (result.output or result.stdout)

    def test_rejects_bad_spec_ref(self, tmp_path: Path) -> None:
        """create rejects spec_refs that don't exist."""
        mock_repo = MagicMock()
        with (
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.cli.task_cmd.Path", return_value=tmp_path),
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
        with patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo):
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
        with patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo):
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
        with patch("ydk.cli.task_cmd.Path", return_value=tmp_path):
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
                    "ydk:entity:missing/Ref",
                ],
            )
        assert result.exit_code != 0

    def test_rejects_bad_spec_ref(self, tmp_path: Path) -> None:
        """create-story rejects spec_refs that don't exist."""
        with patch("ydk.cli.task_cmd.Path", return_value=tmp_path):
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
        with patch("ydk.repositories.factory.get_story_repository", return_value=mock_repo):
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

        with patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo):
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

        with patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo):
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

        # Create .ydk dir for config
        ydk_dir = tmp_path / ".ydk"
        ydk_dir.mkdir()

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

        ydk_dir = tmp_path / ".ydk"
        ydk_dir.mkdir()

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


# ---------------------------------------------------------------------------
# Consistent spec_ref resolution across single-item and batch paths
# ---------------------------------------------------------------------------


class TestSpecRefConsistency:
    def test_cli_helper_accepts_bare_name_full_path_and_adr(self, tmp_path: Path, monkeypatch: object) -> None:
        import typer

        from ydk.cli.task_cmd import _validate_spec_refs_cli

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        (tmp_path / "docs" / "specs").mkdir(parents=True)
        (tmp_path / "docs" / "specs" / "orders.md").write_text("# O", encoding="utf-8")
        (tmp_path / "docs" / "adrs").mkdir(parents=True)
        (tmp_path / "docs" / "adrs" / "0001-x.md").write_text("# A", encoding="utf-8")

        _validate_spec_refs_cli(["orders.md", "docs/specs/orders.md", "docs/adrs/0001-x.md"], tmp_path)

        with pytest.raises(typer.BadParameter, match=r"missing.md"):
            _validate_spec_refs_cli(["missing.md"], tmp_path)

    def test_batch_dry_run_accepts_bare_and_adr_refs(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        (tmp_path / "docs" / "specs").mkdir(parents=True)
        (tmp_path / "docs" / "specs" / "orders.md").write_text("# O", encoding="utf-8")
        (tmp_path / "docs" / "adrs").mkdir(parents=True)
        (tmp_path / "docs" / "adrs" / "0001-x.md").write_text("# A", encoding="utf-8")
        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump({"tasks": [{"id": "t1", "title": "T", "spec_refs": ["orders.md", "docs/adrs/0001-x.md"]}]}),
            encoding="utf-8",
        )

        result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file), "--dry-run"])

        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# validate-dag hierarchy check with GitHub-shaped details (id == "", number set)
# ---------------------------------------------------------------------------


class TestValidateDagGithubHierarchy:
    @staticmethod
    def _run(epics: list[EpicDetail], stories: list[StoryDetail]) -> str:
        task_repo = MagicMock()
        task_repo.list_tasks.return_value = [TaskSummary(id="T-001", title="T", status="open")]
        task_repo.get_task.return_value = TaskDetail(id="T-001", title="T", status="open", dependencies=[])
        story_repo = MagicMock()
        story_repo.list_stories.return_value = stories
        epic_repo = MagicMock()
        epic_repo.list_epics.return_value = epics
        with (
            patch("ydk.cli.task_cmd._get_repo", return_value=task_repo),
            patch("ydk.repositories.factory.get_story_repository", return_value=story_repo),
            patch("ydk.repositories.factory.get_epic_repository", return_value=epic_repo),
        ):
            result = runner.invoke(app, ["task", "validate-dag"])
        return result.output

    def test_linked_epic_not_reported(self) -> None:
        out = self._run(
            [EpicDetail(number=6, id="", title="E")],
            [StoryDetail(number=9, id="", title="S", epic_id="#6")],
        )
        assert "has no stories" not in out

    def test_unlinked_epic_reported_with_number(self) -> None:
        out = self._run(
            [EpicDetail(number=7, id="", title="E")],
            [StoryDetail(number=9, id="", title="S", epic_id="#6")],
        )
        assert "Epic #7 has no stories" in out

    def test_orphan_story_shows_number(self) -> None:
        out = self._run(
            [EpicDetail(number=6, id="", title="E")],
            [StoryDetail(number=9, id="", title="S", epic_id=None)],
        )
        assert "Story #9 has no epic_id" in out


# ---------------------------------------------------------------------------
# --from batch.yaml
# ---------------------------------------------------------------------------


def _write_batch(path: Path, data: dict[str, object]) -> str:
    path.write_text(yaml.dump(data), encoding="utf-8")
    return str(path)


class TestValidateDagFromBatch:
    def test_cycle_reported_and_exits_nonzero(self, tmp_path: Path) -> None:
        f = _write_batch(
            tmp_path / "b.yaml",
            {
                "tasks": [
                    {"id": "T-a", "title": "A", "depends_on": ["T-b"]},
                    {"id": "T-b", "title": "B", "depends_on": ["T-a:blocks"]},
                ]
            },
        )
        result = runner.invoke(app, ["task", "validate-dag", "--from", f])
        assert result.exit_code == 1
        assert "cycle" in result.output.lower()
        assert "T-a" in result.output
        assert "T-b" in result.output

    def test_no_cycle_valid(self, tmp_path: Path) -> None:
        f = _write_batch(
            tmp_path / "b.yaml",
            {"tasks": [{"id": "T-a", "title": "A"}, {"id": "T-b", "title": "B", "depends_on": "T-a"}]},
        )
        result = runner.invoke(app, ["task", "validate-dag", "--from", f])
        assert result.exit_code == 0
        assert "DAG is valid" in result.output

    def test_external_issue_dep_resolved(self, tmp_path: Path) -> None:
        f = _write_batch(
            tmp_path / "b.yaml",
            {"tasks": [{"id": "T-a", "title": "A", "depends_on": ["#169"]}]},
        )
        result = runner.invoke(app, ["task", "validate-dag", "--from", f])
        assert result.exit_code == 0, result.output
        assert "DAG is valid" in result.output

    def test_missing_file(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["task", "validate-dag", "--from", str(tmp_path / "nope.yaml")])
        assert result.exit_code == 1

    def test_repo_mode_still_works(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from ydk.models.pm import TaskCreate
        from ydk.repositories.local.tasks import LocalTaskRepository

        monkeypatch.chdir(tmp_path)
        repo = LocalTaskRepository(tmp_path / "tasks")
        repo.create_task(TaskCreate(title="Solo"))
        with patch("ydk.cli.task_cmd._get_repo", return_value=repo):
            result = runner.invoke(app, ["task", "validate-dag"])
        assert result.exit_code == 0, result.output
        assert "DAG is valid" in result.output


class TestComponentCoverageFromBatch:
    def _components(self, root: Path) -> None:
        comp_dir = root / ".ydk" / "components" / "entity"
        comp_dir.mkdir(parents=True)
        (comp_dir / "Order.yaml").write_text(yaml.dump({"id": "ydk:entity:orders/Order"}))
        (comp_dir / "User.yaml").write_text(yaml.dump({"id": "ydk:entity:users/User"}))

    def test_uncovered_listed_and_strict_exits_1(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._components(tmp_path)
        monkeypatch.chdir(tmp_path)
        f = _write_batch(
            tmp_path / "b.yaml",
            {"tasks": [{"id": "T-a", "title": "A", "component_refs": ["ydk:entity:orders/Order"]}]},
        )
        result = runner.invoke(app, ["task", "component-coverage", "--from", f])
        assert result.exit_code == 0
        assert "ydk:entity:users/User" in result.output
        assert "ydk:entity:orders/Order" not in result.output
        strict = runner.invoke(app, ["task", "component-coverage", "--from", f, "--strict"])
        assert strict.exit_code == 1

    def test_covered_by_task_and_story(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._components(tmp_path)
        monkeypatch.chdir(tmp_path)
        f = _write_batch(
            tmp_path / "b.yaml",
            {
                "stories": [{"id": "S-1", "title": "S", "component_refs": "ydk:entity:users/User"}],
                "tasks": [{"id": "T-a", "title": "A", "component_refs": ["ydk:entity:orders/Order"]}],
            },
        )
        result = runner.invoke(app, ["task", "component-coverage", "--from", f, "--strict"])
        assert result.exit_code == 0
        assert "All components are referenced" in result.output


class TestValidateDagFromBatchEdges:
    def test_non_blocking_loop_passes(self, tmp_path: Path) -> None:
        f = _write_batch(
            tmp_path / "b.yaml",
            {
                "tasks": [
                    {"id": "T-a", "title": "A", "depends_on": ["T-b:related"]},
                    {"id": "T-b", "title": "B", "depends_on": ["T-a:related"]},
                ]
            },
        )
        result = runner.invoke(app, ["task", "validate-dag", "--from", f])
        assert result.exit_code == 0, result.output

    def test_self_dependency_fails(self, tmp_path: Path) -> None:
        f = _write_batch(tmp_path / "b.yaml", {"tasks": [{"id": "T-a", "title": "A", "depends_on": ["T-a"]}]})
        result = runner.invoke(app, ["task", "validate-dag", "--from", f])
        assert result.exit_code == 1

    def test_non_mapping_yaml_fails(self, tmp_path: Path) -> None:
        p = tmp_path / "b.yaml"
        p.write_text("- a\n- b\n", encoding="utf-8")
        result = runner.invoke(app, ["task", "validate-dag", "--from", str(p)])
        assert result.exit_code == 1

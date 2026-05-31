"""Tests for create-batch, --description-file, plan-waves safety, dry-run, and two-pass dep resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import yaml
from typer.testing import CliRunner

from odk.cli import app
from odk.cli.task_cmd import _validate_batch_yaml
from odk.models.pm import EpicDetail, StoryDetail, TaskDetail, TaskSummary

runner = CliRunner()


# -- Issue 1: Two-pass batch creation with placeholder resolution ----------------


class TestTwoPassBatchCreation:
    def test_two_pass_creates_epics_stories_tasks(self, tmp_path: Path) -> None:
        """create-batch creates epics, stories, then tasks with resolved refs."""
        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump(
                {
                    "epics": [
                        {"id": "epic-a", "title": "Phase A", "description": "Bootstrap"},
                    ],
                    "stories": [
                        {"id": "story-a", "epic": "epic-a", "title": "Story A"},
                    ],
                    "tasks": [
                        {"id": "t1", "story": "story-a", "title": "Task 1", "depends_on": []},
                        {"id": "t2", "story": "story-a", "title": "Task 2", "depends_on": ["t1:blocks"]},
                    ],
                }
            ),
            encoding="utf-8",
        )

        mock_epic_repo = MagicMock()
        mock_epic_repo.create_epic.return_value = EpicDetail(id="E-001", number=1, title="Phase A")

        mock_story_repo = MagicMock()
        mock_story_repo.create_story.return_value = StoryDetail(id="S-001", number=1, title="Story A")

        mock_task_repo = MagicMock()
        mock_task_repo.create_task.side_effect = [
            TaskDetail(id="T-001", title="Task 1", status="open"),
            TaskDetail(id="T-002", title="Task 2", status="open"),
        ]

        with (
            patch("odk.cli.task_cmd._get_repo", return_value=mock_task_repo),
            patch("odk.repositories.factory.get_epic_repository", return_value=mock_epic_repo),
            patch("odk.repositories.factory.get_story_repository", return_value=mock_story_repo),
            patch("odk.cli.task_cmd._ensure_labels"),
        ):
            result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file)])

        assert result.exit_code == 0, result.output
        assert mock_epic_repo.create_epic.call_count == 1
        assert mock_story_repo.create_story.call_count == 1
        assert mock_task_repo.create_task.call_count == 2

        # Story should be created with resolved epic ID
        story_call = mock_story_repo.create_story.call_args[0][0]
        assert story_call.epic_id == "E-001"

        # Tasks should be created with resolved story ID
        for call in mock_task_repo.create_task.call_args_list:
            assert call[0][0].story_id == "S-001"

    def test_two_pass_resolves_dependencies(self, tmp_path: Path) -> None:
        """Pass 2 resolves placeholder dep IDs to real IDs via update_frontmatter."""
        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump(
                {
                    "tasks": [
                        {"id": "t1", "title": "Task 1", "depends_on": []},
                        {"id": "t2", "title": "Task 2", "depends_on": ["t1:blocks"]},
                    ],
                }
            ),
            encoding="utf-8",
        )

        mock_task_repo = MagicMock()
        mock_task_repo.create_task.side_effect = [
            TaskDetail(id="T-001", title="Task 1", status="open"),
            TaskDetail(id="T-002", title="Task 2", status="open"),
        ]

        with (
            patch("odk.cli.task_cmd._get_repo", return_value=mock_task_repo),
            patch("odk.repositories.factory.get_epic_repository", return_value=MagicMock()),
            patch("odk.repositories.factory.get_story_repository", return_value=MagicMock()),
            patch("odk.cli.task_cmd._ensure_labels"),
        ):
            result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file)])

        assert result.exit_code == 0, result.output

        # Pass 2: update_frontmatter should be called for t2 with resolved deps
        assert mock_task_repo.update_frontmatter.call_count == 1
        call_args = mock_task_repo.update_frontmatter.call_args
        assert call_args[0][0] == "T-002"  # real ID of t2
        deps = call_args[0][1]["dependencies"]
        assert deps == ["T-001"]  # resolved from "t1" -> "T-001", blocks = bare string


# -- Issue 2: Auto-create labels -----------------------------------------------


class TestAutoCreateLabels:
    def test_ensure_labels_called_during_batch(self, tmp_path: Path) -> None:
        """create-batch calls _ensure_labels before creating issues."""
        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump({"tasks": [{"id": "t1", "title": "Task 1"}]}),
            encoding="utf-8",
        )

        mock_repo = MagicMock()
        mock_repo.create_task.return_value = TaskDetail(id="T-001", title="Task 1", status="open")

        ensure_called = []

        def mock_ensure(repo: object) -> None:
            ensure_called.append(True)

        with (
            patch("odk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("odk.repositories.factory.get_epic_repository", return_value=MagicMock()),
            patch("odk.repositories.factory.get_story_repository", return_value=MagicMock()),
            patch("odk.cli.task_cmd._ensure_labels", side_effect=mock_ensure),
        ):
            result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file)])

        assert result.exit_code == 0, result.output
        assert ensure_called, "_ensure_labels was not called"


# -- Issue 6/7/11: Full batch YAML schema with hierarchy -----------------------


class TestFullBatchSchema:
    def test_batch_with_only_tasks_still_works(self, tmp_path: Path) -> None:
        """Backward compat: create-batch with only tasks key works."""
        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump(
                {
                    "tasks": [
                        {"id": "t1", "title": "Create config.py", "story": "S-001"},
                        {"id": "t2", "title": "Create database.py", "story": "S-001"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        mock_repo = MagicMock()
        mock_repo.create_task.side_effect = [
            TaskDetail(id="T-001", title="Create config.py", status="open"),
            TaskDetail(id="T-002", title="Create database.py", status="open"),
        ]

        with (
            patch("odk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("odk.repositories.factory.get_epic_repository", return_value=MagicMock()),
            patch("odk.repositories.factory.get_story_repository", return_value=MagicMock()),
            patch("odk.cli.task_cmd._ensure_labels"),
        ):
            result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file)])

        assert result.exit_code == 0, result.output
        assert mock_repo.create_task.call_count == 2

    def test_batch_reports_table(self, tmp_path: Path) -> None:
        """create-batch output contains results for each item."""
        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump({"tasks": [{"id": "t1", "title": "Task A", "story": "S-001"}]}),
            encoding="utf-8",
        )

        mock_repo = MagicMock()
        mock_repo.create_task.return_value = TaskDetail(id="T-100", title="Task A", status="open")

        with (
            patch("odk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("odk.repositories.factory.get_epic_repository", return_value=MagicMock()),
            patch("odk.repositories.factory.get_story_repository", return_value=MagicMock()),
            patch("odk.cli.task_cmd._ensure_labels"),
        ):
            result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file)])

        assert result.exit_code == 0, result.output
        assert "T-100" in result.output
        assert "t1" in result.output  # placeholder ID shown in table


# -- Issue 10: Dry-run validation -----------------------------------------------


class TestDryRunValidation:
    def test_dry_run_catches_errors(self, tmp_path: Path) -> None:
        """--dry-run validates YAML and reports errors without creating issues."""
        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump(
                {
                    "tasks": [
                        {"id": "t1", "title": "Task 1"},
                        {"id": "t2", "title": "Task 2", "depends_on": ["nonexistent:blocks"]},
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file), "--dry-run"])

        assert result.exit_code != 0
        assert "ERROR" in result.output
        assert "nonexistent" in result.output

    def test_dry_run_no_issues_created(self, tmp_path: Path) -> None:
        """--dry-run does not create any issues."""
        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump(
                {
                    "epics": [{"id": "e1", "title": "Epic 1"}],
                    "stories": [{"id": "s1", "epic": "e1", "title": "Story 1"}],
                    "tasks": [{"id": "t1", "story": "s1", "title": "Task 1"}],
                }
            ),
            encoding="utf-8",
        )

        mock_repo = MagicMock()
        with patch("odk.cli.task_cmd._get_repo", return_value=mock_repo):
            result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file), "--dry-run"])

        assert result.exit_code == 0
        assert "Dry run" in result.output
        assert mock_repo.create_task.call_count == 0

    def test_dry_run_shows_summary(self, tmp_path: Path) -> None:
        """--dry-run prints what would be created."""
        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump(
                {
                    "epics": [{"id": "e1", "title": "Epic 1"}],
                    "tasks": [{"id": "t1", "title": "Task 1"}],
                }
            ),
            encoding="utf-8",
        )

        result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file), "--dry-run"])

        assert result.exit_code == 0
        assert "Epic 1" in result.output
        assert "Task 1" in result.output

    def test_validate_batch_yaml_self_dependency(self) -> None:
        """_validate_batch_yaml catches self-dependencies."""
        errors = _validate_batch_yaml({"tasks": [{"id": "t1", "title": "T1", "depends_on": ["t1:blocks"]}]})
        assert any("self-dependency" in e for e in errors)

    def test_validate_batch_yaml_invalid_dep_type(self) -> None:
        """_validate_batch_yaml catches invalid dependency types."""
        errors = _validate_batch_yaml(
            {
                "tasks": [
                    {"id": "t1", "title": "T1"},
                    {"id": "t2", "title": "T2", "depends_on": ["t1:invalid-type"]},
                ]
            }
        )
        assert any("invalid dependency type" in e for e in errors)

    def test_validate_batch_yaml_missing_title(self) -> None:
        """_validate_batch_yaml catches missing titles."""
        errors = _validate_batch_yaml({"tasks": [{"id": "t1"}]})
        assert any("missing 'title'" in e for e in errors)


# -- Issue 12: --dry-run on individual create commands --------------------------


class TestIndividualDryRun:
    def test_create_task_dry_run(self) -> None:
        """create --dry-run shows what would be created without calling API."""
        result = runner.invoke(
            app,
            [
                "task",
                "create",
                "--title",
                "My Task",
                "--story",
                "S-001",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "Dry run" in result.output
        assert "My Task" in result.output

    def test_create_epic_dry_run(self) -> None:
        """create-epic --dry-run shows what would be created."""
        result = runner.invoke(
            app,
            ["task", "create-epic", "--title", "My Epic", "--dry-run"],
        )
        assert result.exit_code == 0
        assert "Dry run" in result.output
        assert "My Epic" in result.output

    def test_create_story_dry_run(self) -> None:
        """create-story --dry-run shows what would be created."""
        result = runner.invoke(
            app,
            ["task", "create-story", "--title", "My Story", "--epic", "E-001", "--dry-run"],
        )
        assert result.exit_code == 0
        assert "Dry run" in result.output
        assert "My Story" in result.output


# -- Issue 4: validate-dag separates unresolved from cycles ----------------------


class TestValidateDagErrorMessages:
    def test_unresolved_deps_show_specific_error(self) -> None:
        """validate-dag shows 'Unresolved dependency references' not 'cycle detected'."""
        from odk.core.task_validator import validate_dag
        from odk.models.task import Task

        tasks = [
            Task(id="A", title="A", depends_on=["MISSING"]),
            Task(id="B", title="B"),
        ]
        result = validate_dag(tasks)
        assert result.valid is False
        assert result.error is not None
        assert "Unresolved" in result.error
        assert result.cycles is None  # Not a cycle issue

    def test_cycles_still_detected(self) -> None:
        """validate-dag still reports cycles correctly."""
        from odk.core.task_validator import validate_dag
        from odk.models.task import Task

        tasks = [
            Task(id="A", title="A", depends_on=["B"]),
            Task(id="B", title="B", depends_on=["A"]),
        ]
        result = validate_dag(tasks)
        assert result.valid is False
        assert result.error is None  # Cycles, not unresolved
        assert result.cycles is not None
        assert len(result.cycles) > 0


# -- Issue 5: deps-met for unresolvable deps ------------------------------------


class TestUnresolvableDeps:
    def test_unresolvable_dep_shows_not_met(self) -> None:
        """list_tasks marks deps as not met when dependency doesn't exist."""
        from tests.cli.test_task_cmd_batch import _setup_local_repo

        repo, _tmp = _setup_local_repo()
        # Create manifest with a task that depends on nonexistent
        manifest_data = repo._manifest.load()
        manifest_data["tasks"]["T-001"] = {
            "title": "Task A",
            "status": "open",
            "dependencies": ["T-999"],  # Does not exist
        }
        repo._manifest.save(manifest_data)

        tasks = repo.list_tasks(state="open")
        assert len(tasks) == 1
        assert tasks[0].dependencies_met is False


# -- Issue 3: config set with JSON list values ----------------------------------


class TestConfigSetJSON:
    def test_config_set_json_list(self, tmp_path: Path, monkeypatch: object) -> None:
        """config set parses JSON list values."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        config_dir = tmp_path / ".odk"
        config_dir.mkdir()
        from odk.core.config import DEFAULT_CONFIG

        config_path = config_dir / "config.yaml"
        config_path.write_text(yaml.dump(DEFAULT_CONFIG, default_flow_style=False))

        result = runner.invoke(
            app,
            ["config", "set", "task_management.coverage_exclude", '["08-glossary.md", "09-appendix.md"]'],
        )
        assert result.exit_code == 0, result.output

        raw = yaml.safe_load(config_path.read_text())
        assert raw["task_management"]["coverage_exclude"] == ["08-glossary.md", "09-appendix.md"]


# -- Existing tests (preserved) ------------------------------------------------


class TestCreateBatch:
    def test_create_batch_from_yaml(self, tmp_path: Path, monkeypatch: object) -> None:
        """create-batch reads YAML and creates all tasks."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        # Create spec files referenced in the batch YAML
        spec_dir = tmp_path / "docs" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "01-core-domain.md").write_text("# Core Domain", encoding="utf-8")

        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump(
                {
                    "tasks": [
                        {
                            "id": "t1",
                            "title": "Create config.py",
                            "story": "S-001",
                            "component_refs": ["odk:crosscut:config/settings"],
                            "spec_refs": ["docs/specs/01-core-domain.md"],
                            "depends_on": [],
                            "test_strategy": "Unit test for settings loading",
                        },
                        {
                            "id": "t2",
                            "title": "Create database.py",
                            "story": "S-001",
                            "component_refs": ["odk:contract:data/DatabaseSession"],
                            "spec_refs": ["docs/specs/01-core-domain.md"],
                            "depends_on": ["t1:blocks"],
                            "test_strategy": "Integration test",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        mock_repo = MagicMock()
        mock_repo.create_task.side_effect = [
            TaskDetail(id="T-001", title="Create config.py", status="open"),
            TaskDetail(id="T-002", title="Create database.py", status="open"),
        ]

        with (
            patch("odk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("odk.repositories.factory.get_epic_repository", return_value=MagicMock()),
            patch("odk.repositories.factory.get_story_repository", return_value=MagicMock()),
            patch("odk.cli.task_cmd._ensure_labels"),
        ):
            result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file)])

        assert result.exit_code == 0, result.output
        assert mock_repo.create_task.call_count == 2
        assert "T-001" in result.output
        assert "T-002" in result.output

    def test_create_batch_missing_file(self) -> None:
        """create-batch exits 1 when file does not exist."""
        result = runner.invoke(app, ["task", "create-batch", "--from", "/nonexistent/batch.yaml"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_create_batch_invalid_yaml(self, tmp_path: Path) -> None:
        """create-batch exits 1 for missing required keys."""
        batch_file = tmp_path / "bad.yaml"
        batch_file.write_text("foo: bar\n", encoding="utf-8")

        result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file)])
        assert result.exit_code != 0

    def test_create_batch_partial_failure(self, tmp_path: Path) -> None:
        """create-batch reports failures per task."""
        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump(
                {
                    "tasks": [
                        {"id": "t1", "title": "Good task", "story": "S-001"},
                        {"id": "t2", "title": "Bad task", "story": "S-002"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        mock_repo = MagicMock()
        mock_repo.create_task.side_effect = [
            TaskDetail(id="T-001", title="Good task", status="open"),
            ValueError("duplicate title"),
        ]

        with (
            patch("odk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("odk.repositories.factory.get_epic_repository", return_value=MagicMock()),
            patch("odk.repositories.factory.get_story_repository", return_value=MagicMock()),
            patch("odk.cli.task_cmd._ensure_labels"),
        ):
            result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file)])

        assert result.exit_code != 0
        assert "FAILED" in result.output
        assert "T-001" in result.output


# -- Issue 12: --description-file ---------------------------------------------


class TestDescriptionFile:
    def test_description_from_file(self, tmp_path: Path) -> None:
        """--description-file reads description from a file."""
        desc_file = tmp_path / "desc.md"
        desc_file.write_text("A long detailed description\nwith multiple lines.", encoding="utf-8")

        mock_repo = MagicMock()
        mock_repo.create_task.return_value = TaskDetail(id="T-010", title="My task", status="open")

        with patch("odk.cli.task_cmd._get_repo", return_value=mock_repo):
            result = runner.invoke(
                app,
                [
                    "task",
                    "create",
                    "--title",
                    "My task",
                    "--story",
                    "S-001",
                    "--description-file",
                    str(desc_file),
                ],
            )

        assert result.exit_code == 0, result.output
        call_args = mock_repo.create_task.call_args[0][0]
        assert "A long detailed description" in call_args.description
        assert "with multiple lines" in call_args.description

    def test_description_and_file_mutually_exclusive(self, tmp_path: Path) -> None:
        """--description and --description-file cannot be used together."""
        desc_file = tmp_path / "desc.md"
        desc_file.write_text("content", encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "task",
                "create",
                "--title",
                "Test",
                "--story",
                "S-001",
                "--description",
                "inline desc",
                "--description-file",
                str(desc_file),
            ],
        )

        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

    def test_description_file_not_found(self) -> None:
        """--description-file with nonexistent file exits with error."""
        result = runner.invoke(
            app,
            [
                "task",
                "create",
                "--title",
                "Test",
                "--story",
                "S-001",
                "--description-file",
                "/nonexistent/file.md",
            ],
        )

        assert result.exit_code != 0
        assert "not found" in result.output


# -- Issue 10: plan-waves unresolved dependency warning -----------------------


class TestPlanWavesUnresolvedDeps:
    def test_plan_waves_warns_on_unresolved_deps(self) -> None:
        """plan-waves warns when a task depends on a non-existent task."""
        mock_repo = MagicMock()
        t1 = TaskDetail(id="T-001", title="First", status="open", dependencies=[])
        t2 = TaskDetail(id="T-002", title="Second", status="open", dependencies=["T-999"])
        mock_repo.list_tasks.return_value = [
            TaskSummary(id="T-001", title="First", status="open", dependencies_met=True),
            TaskSummary(id="T-002", title="Second", status="open", dependencies_met=True),
        ]
        mock_repo.get_task.side_effect = lambda tid: {"T-001": t1, "T-002": t2}[tid]

        with patch("odk.cli.task_cmd._get_repo", return_value=mock_repo):
            result = runner.invoke(app, ["task", "plan-waves", "--agents", "1"])

        assert result.exit_code == 0
        assert "Warning" in result.output
        assert "T-999" in result.output

    def test_plan_waves_no_warning_when_deps_resolved(self) -> None:
        """plan-waves does not warn when all deps are in the task set."""
        mock_repo = MagicMock()
        t1 = TaskDetail(id="T-001", title="First", status="open", dependencies=[])
        t2 = TaskDetail(id="T-002", title="Second", status="open", dependencies=["T-001"])
        mock_repo.list_tasks.return_value = [
            TaskSummary(id="T-001", title="First", status="open", dependencies_met=True),
            TaskSummary(id="T-002", title="Second", status="open", dependencies_met=True),
        ]
        mock_repo.get_task.side_effect = lambda tid: {"T-001": t1, "T-002": t2}[tid]

        with patch("odk.cli.task_cmd._get_repo", return_value=mock_repo):
            result = runner.invoke(app, ["task", "plan-waves", "--agents", "1"])

        assert result.exit_code == 0
        assert "Warning" not in result.output


# -- Helpers -------------------------------------------------------------------


def _setup_local_repo() -> tuple:  # type: ignore[type-arg]
    """Create a temporary LocalTaskRepository for testing."""
    import tempfile
    from pathlib import Path

    from odk.repositories.local.tasks import LocalTaskRepository

    tmp = Path(tempfile.mkdtemp())
    odk_dir = tmp / ".odk"
    odk_dir.mkdir(parents=True)
    tasks_dir = odk_dir / "tasks"
    tasks_dir.mkdir()
    # Write empty manifest
    manifest_path = odk_dir / "manifest.yaml"
    manifest_path.write_text(
        yaml.dump({"epics": {}, "stories": {}, "tasks": {}, "next_ids": {"epic": 1, "story": 1, "task": 1}}),
        encoding="utf-8",
    )
    repo = LocalTaskRepository(odk_dir)
    return repo, tmp

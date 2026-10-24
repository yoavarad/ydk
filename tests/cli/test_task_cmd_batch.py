"""Tests for create-batch, --description-file, plan-waves safety, dry-run, and two-pass dep resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import yaml
from typer.testing import CliRunner

from ydk.cli import app
from ydk.cli.task_cmd import _validate_batch_yaml
from ydk.models.pm import EpicDetail, StoryDetail, StorySummary, TaskDetail, TaskSummary

runner = CliRunner()


def _story_repo(*ids: str) -> MagicMock:
    repo = MagicMock()
    repo.list_stories.return_value = [StorySummary(id=i, title=i) for i in ids]
    return repo


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
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_task_repo),
            patch("ydk.repositories.factory.get_epic_repository", return_value=mock_epic_repo),
            patch("ydk.repositories.factory.get_story_repository", return_value=mock_story_repo),
            patch("ydk.cli.task_cmd._ensure_labels"),
            patch("pathlib.Path.write_text", autospec=True) as mock_write_text,
        ):
            result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file)])

        assert result.exit_code == 0, result.output
        assert mock_epic_repo.create_epic.call_count == 1
        assert mock_story_repo.create_story.call_count == 1
        assert mock_task_repo.create_task.call_count == 2

        mapping_calls = [c for c in mock_write_text.call_args_list if c.args[0].name == "batch-mapping.json"]
        assert mapping_calls
        assert all(c.kwargs.get("encoding") == "utf-8" for c in mapping_calls)

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
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_task_repo),
            patch("ydk.repositories.factory.get_epic_repository", return_value=MagicMock()),
            patch("ydk.repositories.factory.get_story_repository", return_value=MagicMock()),
            patch("ydk.cli.task_cmd._ensure_labels"),
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
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.repositories.factory.get_epic_repository", return_value=MagicMock()),
            patch("ydk.repositories.factory.get_story_repository", return_value=MagicMock()),
            patch("ydk.cli.task_cmd._ensure_labels", side_effect=mock_ensure),
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

        mock_story_repo = MagicMock()
        mock_story_repo.list_stories.return_value = [StorySummary(id="S-001", title="s")]

        with (
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.repositories.factory.get_epic_repository", return_value=MagicMock()),
            patch("ydk.repositories.factory.get_story_repository", return_value=mock_story_repo),
            patch("ydk.cli.task_cmd._ensure_labels"),
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
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.repositories.factory.get_epic_repository", return_value=MagicMock()),
            patch("ydk.repositories.factory.get_story_repository", return_value=_story_repo("S-001", "S-002")),
            patch("ydk.cli.task_cmd._ensure_labels"),
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
        with patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo):
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

    def test_validate_batch_yaml_accepts_existing_ids(self) -> None:
        """existing_ids satisfy depends_on, with and without a type suffix."""
        data = {"tasks": [{"id": "t1", "title": "T1", "depends_on": ["T-001", "T-002:validates"]}]}
        assert _validate_batch_yaml(data, existing_ids={"T-001", "T-002"}) == []

    def test_validate_batch_yaml_unknown_id_still_errors_with_existing_ids(self) -> None:
        """IDs in neither the YAML nor existing_ids stay 'undefined ID'."""
        data = {"tasks": [{"id": "t1", "title": "T1", "depends_on": ["T-999"]}]}
        errors = _validate_batch_yaml(data, existing_ids={"T-001"})
        assert any("undefined ID 'T-999'" in e for e in errors)

    def test_dry_run_accepts_existing_task_ids(self, tmp_path: Path) -> None:
        """--dry-run accepts depends_on IDs that exist in the repo."""
        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump({"tasks": [{"id": "t1", "title": "T1", "depends_on": ["T-001", "T-002:validates"]}]}),
            encoding="utf-8",
        )
        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = [TaskSummary(id="T-001", title="a"), TaskSummary(id="T-002", title="b")]
        with patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo):
            result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file), "--dry-run"])
        assert result.exit_code == 0, result.output

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


def _make_manifest(root: Path, ref_dir: str = "entity/orders", name: str = "Order") -> None:
    comp = root / ".ydk" / "components" / ref_dir
    comp.mkdir(parents=True)
    (comp / f"{name}.yaml").write_text("id: x", encoding="utf-8")


class TestBatchRefValidation:
    """component_refs and task->story refs are validated before any API call."""

    def test_unknown_task_component_ref(self, tmp_path: Path) -> None:
        data = {"tasks": [{"id": "t1", "title": "T1", "component_refs": ["ydk:entity:orders/Order"]}]}
        errors = _validate_batch_yaml(data, project_root=tmp_path)
        assert any("not found" in e and "ydk:entity:orders/Order" in e for e in errors)

    def test_unknown_story_component_ref(self, tmp_path: Path) -> None:
        data = {"stories": [{"id": "s1", "title": "S1", "component_refs": ["ydk:entity:orders/Order"]}]}
        errors = _validate_batch_yaml(data, project_root=tmp_path)
        assert any("s1" in e and "not found" in e for e in errors)

    def test_valid_component_ref_with_manifest(self, tmp_path: Path) -> None:
        _make_manifest(tmp_path)
        data = {
            "stories": [{"id": "s1", "title": "S1", "component_refs": ["ydk:entity:orders/Order"]}],
            "tasks": [{"id": "t1", "title": "T1", "story": "s1", "component_refs": ["ydk:entity:orders/Order"]}],
        }
        assert _validate_batch_yaml(data, project_root=tmp_path) == []

    def test_unknown_story_ref(self) -> None:
        errors = _validate_batch_yaml({"tasks": [{"id": "t1", "title": "T1", "story": "S-999"}]})
        assert any("S-999" in e and "undefined story" in e for e in errors)

    def test_story_ref_defined_in_yaml(self) -> None:
        data = {"stories": [{"id": "s1", "title": "S"}], "tasks": [{"id": "t1", "title": "T", "story": "s1"}]}
        assert _validate_batch_yaml(data) == []

    def test_story_ref_in_existing_ids(self) -> None:
        data = {"tasks": [{"id": "t1", "title": "T", "story": "S-001"}]}
        assert _validate_batch_yaml(data, existing_ids={"S-001"}) == []

    def test_valid_dep_type(self) -> None:
        data = {"tasks": [{"id": "a", "title": "A"}, {"id": "b", "title": "B", "depends_on": ["a:validates"]}]}
        assert _validate_batch_yaml(data) == []

    def test_non_mapping_entries(self) -> None:
        errors = _validate_batch_yaml({"epics": ["x"], "stories": [42], "tasks": [None]})
        assert len(errors) == 3
        assert all("not a mapping" in e for e in errors)

    def test_dry_run_exits_1_for_unknown_component_ref(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump({"tasks": [{"id": "t1", "title": "T1", "component_refs": ["ydk:entity:orders/Order"]}]}),
            encoding="utf-8",
        )
        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = []
        with patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo):
            result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file), "--dry-run"])
        assert result.exit_code == 1, result.output

    def test_dry_run_exits_1_for_unknown_story(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(yaml.dump({"tasks": [{"id": "t1", "title": "T1", "story": "S-9"}]}), encoding="utf-8")
        mock_repo = MagicMock()
        mock_repo.list_tasks.return_value = []
        with patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo):
            result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file), "--dry-run"])
        assert result.exit_code == 1, result.output


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
        from ydk.core.task_validator import validate_dag
        from ydk.models.task import Task

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
        from ydk.core.task_validator import validate_dag
        from ydk.models.task import Task

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
        config_dir = tmp_path / ".ydk"
        config_dir.mkdir()
        from ydk.core.config import DEFAULT_CONFIG

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

        _make_manifest(tmp_path, "crosscut/config", "settings")
        _make_manifest(tmp_path, "contract/data", "DatabaseSession")
        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump(
                {
                    "tasks": [
                        {
                            "id": "t1",
                            "title": "Create config.py",
                            "story": "S-001",
                            "component_refs": ["ydk:crosscut:config/settings"],
                            "spec_refs": ["docs/specs/01-core-domain.md"],
                            "depends_on": [],
                            "test_strategy": "Unit test for settings loading",
                        },
                        {
                            "id": "t2",
                            "title": "Create database.py",
                            "story": "S-001",
                            "component_refs": ["ydk:contract:data/DatabaseSession"],
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
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.repositories.factory.get_epic_repository", return_value=MagicMock()),
            patch("ydk.repositories.factory.get_story_repository", return_value=_story_repo("S-001", "S-002")),
            patch("ydk.cli.task_cmd._ensure_labels"),
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
            patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo),
            patch("ydk.repositories.factory.get_epic_repository", return_value=MagicMock()),
            patch("ydk.repositories.factory.get_story_repository", return_value=_story_repo("S-001", "S-002")),
            patch("ydk.cli.task_cmd._ensure_labels"),
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

        with patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo):
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

        with patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo):
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

        with patch("ydk.cli.task_cmd._get_repo", return_value=mock_repo):
            result = runner.invoke(app, ["task", "plan-waves", "--agents", "1"])

        assert result.exit_code == 0
        assert "Warning" not in result.output


class TestScaffoldBatch:
    def test_writes_output_with_utf8_encoding(self, tmp_path: Path, monkeypatch: object) -> None:
        from ydk.models.todo import TodoItem

        monkeypatch.chdir(tmp_path)
        mock_mgr = MagicMock()
        mock_mgr.list_todos.return_value = [
            TodoItem(id="YDK-TODO-1", file="app/core/services/billing/service.py", line=10, method="charge"),
        ]

        output_path = tmp_path / "batch-tasks.yaml"

        with (
            patch("ydk.core.todo_manager.TodoManager", return_value=mock_mgr),
            patch("pathlib.Path.write_text", autospec=True) as mock_write_text,
        ):
            result = runner.invoke(app, ["task", "scaffold-batch", "--output", str(output_path)])

        assert result.exit_code == 0, result.output
        assert mock_write_text.call_args.kwargs.get("encoding") == "utf-8"

    @staticmethod
    def _final_task(tmp_path: Path, monkeypatch: object, stack: str | None) -> dict:
        from ydk.models.todo import TodoItem

        monkeypatch.chdir(tmp_path)
        if stack is not None:
            (tmp_path / ".ydk").mkdir()
            (tmp_path / ".ydk" / "config.yaml").write_text(
                yaml.dump({"project": {"name": "p", "stack": stack}}), encoding="utf-8"
            )
        mock_mgr = MagicMock()
        mock_mgr.list_todos.return_value = [TodoItem(id="YDK-TODO-1", file="internal/svc/x.go", line=3, method="Do")]
        output_path = tmp_path / "batch-tasks.yaml"
        with patch("ydk.core.todo_manager.TodoManager", return_value=mock_mgr):
            result = runner.invoke(app, ["task", "scaffold-batch", "--output", str(output_path)])
        assert result.exit_code == 0, result.output
        data = yaml.safe_load(output_path.read_text(encoding="utf-8"))
        return next(t for t in data["tasks"] if t["id"] == "T-FINAL")

    def test_tfinal_python_criteria_unchanged(self, tmp_path: Path, monkeypatch: object) -> None:
        final = self._final_task(tmp_path, monkeypatch, None)
        assert final["title"] == "Final verification: all tests pass, zero xfail"
        assert final["acceptance_criteria"] == [
            "Zero @pytest.mark.xfail in test suite",
            "Zero NotImplementedError in services",
            "All E2E tests pass",
            "Full ruff + ty clean",
        ]

    def test_tfinal_config_resolved_from_project_root_in_subdir(self, tmp_path: Path, monkeypatch: object) -> None:
        (tmp_path / ".ydk").mkdir()
        (tmp_path / ".ydk" / "config.yaml").write_text(
            yaml.dump({"project": {"name": "p", "stack": "go"}}), encoding="utf-8"
        )
        sub = tmp_path / "internal" / "svc"
        sub.mkdir(parents=True)
        final = self._final_task(sub, monkeypatch, None)
        assert "gofmt + go vet clean" in final["acceptance_criteria"]

    def test_tfinal_go_stack_lists_go_criteria(self, tmp_path: Path, monkeypatch: object) -> None:
        final = self._final_task(tmp_path, monkeypatch, "go")
        text = " ".join([final["title"], final["test_strategy"], *final["acceptance_criteria"]])
        assert 'panic("not implemented")' in text
        assert "gofmt + go vet clean" in final["acceptance_criteria"]
        for python_tool in ("ruff", "pytest", "xfail", "NotImplementedError"):
            assert python_tool not in text


# -- Helpers -------------------------------------------------------------------


def _setup_local_repo() -> tuple:  # type: ignore[type-arg]
    """Create a temporary LocalTaskRepository for testing."""
    import tempfile
    from pathlib import Path

    from ydk.repositories.local.tasks import LocalTaskRepository

    tmp = Path(tempfile.mkdtemp())
    ydk_dir = tmp / ".ydk"
    ydk_dir.mkdir(parents=True)
    tasks_dir = ydk_dir / "tasks"
    tasks_dir.mkdir()
    # Write empty manifest
    manifest_path = ydk_dir / "manifest.yaml"
    manifest_path.write_text(
        yaml.dump({"epics": {}, "stories": {}, "tasks": {}, "next_ids": {"epic": 1, "story": 1, "task": 1}}),
        encoding="utf-8",
    )
    repo = LocalTaskRepository(ydk_dir)
    return repo, tmp


# -- Issue 504: string-form refs / acceptance / depends_on ----------------------


def _real_batch(tmp_path: Path, monkeypatch, data: dict, extra: list[str] | None = None):  # type: ignore[no-untyped-def,type-arg]
    """Run create-batch against a real local repository in tmp_path."""
    from ydk.repositories.factory import get_task_repository

    monkeypatch.chdir(tmp_path)
    batch_file = tmp_path / "batch504.yaml"
    batch_file.write_text(yaml.dump(data), encoding="utf-8")
    result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file), *(extra or [])])
    repo = get_task_repository()
    tasks = {}
    for item in repo.list_tasks(state="all"):
        tasks[item.title] = repo.get_task(item.id)
    return result, tasks


class TestStringFormBatchFields:
    def test_string_forms_created_on_local_backend(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        _make_manifest(tmp_path, "crosscut/config", "settings")
        _make_manifest(tmp_path, "contract/data", "Session")
        (tmp_path / "docs" / "specs").mkdir(parents=True)
        (tmp_path / "docs" / "specs" / "a.md").write_text("# a", encoding="utf-8")
        (tmp_path / "docs" / "specs" / "b.md").write_text("# b", encoding="utf-8")
        data = {
            "tasks": [
                {
                    "id": "t1",
                    "title": "A",
                    "component_refs": "ydk:crosscut:config/settings, ydk:contract:data/Session",
                    "spec_refs": "a.md, b.md",
                    "acceptance": "do the thing, really",
                },
                {"id": "t2", "title": "B", "depends_on": "t1, t1:related"},
            ],
        }
        result, tasks = _real_batch(tmp_path, monkeypatch, data)
        assert result.exit_code == 0, result.output
        t1 = tasks["A"]
        assert t1.component_refs == ["ydk:crosscut:config/settings", "ydk:contract:data/Session"]
        assert t1.spec_refs == ["a.md", "b.md"]
        assert [getattr(c, "text", c) for c in t1.acceptance_criteria] == ["do the thing, really"]
        t2 = tasks["B"]
        assert len(t2.dependencies) == 2

    def test_list_forms_still_work_and_drop_null_items(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        data = {
            "tasks": [
                {"id": "t1", "title": "A", "acceptance": ["one", None, "two"]},
                {"id": "t2", "title": "B", "depends_on": [None, "t1"], "acceptance": [None]},
            ],
        }
        result, tasks = _real_batch(tmp_path, monkeypatch, data)
        assert result.exit_code == 0, result.output
        assert [getattr(c, "text", c) for c in tasks["A"].acceptance_criteria] == ["one", "two"]
        t2 = tasks["B"]
        assert t2.acceptance_criteria == []
        assert len(t2.dependencies) == 1

    def test_whitespace_only_acceptance_is_empty(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        data = {"tasks": [{"id": "t1", "title": "A", "acceptance": "   "}]}
        result, tasks = _real_batch(tmp_path, monkeypatch, data)
        assert result.exit_code == 0, result.output
        assert tasks["A"].acceptance_criteria == []

    def test_dry_run_rejects_invalid_types(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        data = {"tasks": [{"id": "t1", "title": "A", "acceptance": 7}]}
        result, _ = _real_batch(tmp_path, monkeypatch, data, ["--dry-run"])
        assert result.exit_code == 1
        assert "acceptance" in result.output

    def test_missing_string_spec_ref_reported_on_disk_check(self, tmp_path: Path) -> None:
        data = {"tasks": [{"id": "t1", "title": "A", "spec_refs": "nope.md, also-nope.md"}]}
        errors = _validate_batch_yaml(data, project_root=tmp_path)
        assert sum("spec_ref" in e for e in errors) == 2

    def test_comma_split_spec_refs_valid_when_present(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("# a", encoding="utf-8")
        (tmp_path / "b.md").write_text("# b", encoding="utf-8")
        data = {"tasks": [{"id": "t1", "title": "A", "spec_refs": "a.md,b.md"}]}
        assert _validate_batch_yaml(data, project_root=tmp_path) == []

    def test_list_form_spec_ref_with_comma_kept_whole(self, tmp_path: Path) -> None:
        (tmp_path / "a,b.md").write_text("# ab", encoding="utf-8")
        data = {"tasks": [{"id": "t1", "title": "A", "spec_refs": ["a,b.md"]}]}
        assert _validate_batch_yaml(data, project_root=tmp_path) == []

    def test_validation_rejects_non_str_list(self) -> None:
        data = {
            "epics": [{"id": "e1", "title": "E", "spec_refs": 5}],
            "stories": [{"id": "s1", "title": "S", "acceptance": 1, "component_refs": {"a": 1}}],
            "tasks": [
                {"id": "t1", "title": "A", "component_refs": 5, "spec_refs": {"a": 1}, "acceptance": 7, "depends_on": 3}
            ],
        }
        errors = _validate_batch_yaml(data)
        assert any("Epic 'e1'" in e and "spec_refs" in e for e in errors)
        assert any("Story 's1'" in e and "acceptance" in e for e in errors)
        assert any("Story 's1'" in e and "component_refs" in e for e in errors)
        for field in ("component_refs", "spec_refs", "acceptance", "depends_on"):
            assert any("Task 't1'" in e and field in e for e in errors), (field, errors)

    def test_validation_accepts_string_forms(self) -> None:
        data = {
            "tasks": [
                {"id": "t1", "title": "A"},
                {"id": "t2", "title": "B", "depends_on": "t1", "acceptance": "x"},
            ],
        }
        assert _validate_batch_yaml(data) == []


class TestDryRunCycles:
    def test_dry_run_reports_cycle_as_error(self, tmp_path: Path) -> None:
        batch_file = tmp_path / "batch.yaml"
        batch_file.write_text(
            yaml.dump(
                {
                    "tasks": [
                        {"id": "T-a", "title": "A", "depends_on": ["T-b"]},
                        {"id": "T-b", "title": "B", "depends_on": ["T-a"]},
                    ]
                }
            ),
            encoding="utf-8",
        )
        result = runner.invoke(app, ["task", "create-batch", "--from", str(batch_file), "--dry-run"])
        assert result.exit_code == 1
        assert "ERROR" in result.output
        assert "T-a" in result.output

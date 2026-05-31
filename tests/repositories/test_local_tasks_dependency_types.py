"""Tests for serialization/deserialization of typed dependencies in local tasks."""

from pathlib import Path

from odk.models.pm import Dependency, DependencyType, TaskCreate
from odk.repositories.local.frontmatter import parse_frontmatter
from odk.repositories.local.tasks import LocalTaskRepository


def _make_task(**overrides) -> TaskCreate:  # type: ignore[no-untyped-def]
    defaults: dict[str, object] = {
        "title": "Test task",
        "story_id": "S-001",
        "spec_refs": [],
        "dependencies": [],
        "description": "A test task.",
        "acceptance_criteria": [],
        "test_strategy": "",
    }
    defaults.update(overrides)
    return TaskCreate(**defaults)


class TestSerializeTypedDeps:
    def test_bare_strings_serialize_as_plain_list(self, tmp_path: Path) -> None:
        """Bare string deps should serialize to simple YAML list for compatibility."""
        repo = LocalTaskRepository(tmp_path)
        detail = repo.create_task(_make_task(dependencies=["T-999", "T-888"]))

        file_path = tmp_path / "tasks" / f"{detail.id}.md"
        fm, _ = parse_frontmatter(file_path.read_text(encoding="utf-8"))
        assert fm["dependencies"] == ["T-999", "T-888"]

    def test_typed_deps_serialize_as_dicts(self, tmp_path: Path) -> None:
        dep = Dependency(task_id="T-999", type=DependencyType.VALIDATES)
        repo = LocalTaskRepository(tmp_path)
        detail = repo.create_task(_make_task(dependencies=[dep]))

        file_path = tmp_path / "tasks" / f"{detail.id}.md"
        fm, _ = parse_frontmatter(file_path.read_text(encoding="utf-8"))
        assert len(fm["dependencies"]) == 1
        assert fm["dependencies"][0]["task_id"] == "T-999"
        assert fm["dependencies"][0]["type"] == "validates"

    def test_mixed_deps_serialize_correctly(self, tmp_path: Path) -> None:
        dep = Dependency(task_id="T-888", type=DependencyType.CAUSED_BY)
        repo = LocalTaskRepository(tmp_path)
        detail = repo.create_task(_make_task(dependencies=["T-999", dep]))

        file_path = tmp_path / "tasks" / f"{detail.id}.md"
        fm, _ = parse_frontmatter(file_path.read_text(encoding="utf-8"))
        assert fm["dependencies"][0] == "T-999"
        assert fm["dependencies"][1]["task_id"] == "T-888"
        assert fm["dependencies"][1]["type"] == "caused-by"


class TestDeserializeTypedDeps:
    def test_old_format_bare_strings_read_back(self, tmp_path: Path) -> None:
        """Backward compat: existing files with bare strings still load."""
        repo = LocalTaskRepository(tmp_path)
        detail = repo.create_task(_make_task(dependencies=["T-999"]))
        read_back = repo.get_task(detail.id)
        assert read_back.dependencies == ["T-999"]

    def test_typed_deps_round_trip(self, tmp_path: Path) -> None:
        dep = Dependency(task_id="T-999", type=DependencyType.VALIDATES)
        repo = LocalTaskRepository(tmp_path)
        detail = repo.create_task(_make_task(dependencies=[dep]))

        read_back = repo.get_task(detail.id)
        assert len(read_back.dependencies) == 1
        assert isinstance(read_back.dependencies[0], Dependency)
        assert read_back.dependencies[0].task_id == "T-999"
        assert read_back.dependencies[0].type == DependencyType.VALIDATES

    def test_mixed_deps_round_trip(self, tmp_path: Path) -> None:
        dep = Dependency(task_id="T-888", type=DependencyType.WAITS_FOR)
        repo = LocalTaskRepository(tmp_path)
        detail = repo.create_task(_make_task(dependencies=["T-999", dep]))

        read_back = repo.get_task(detail.id)
        assert read_back.dependencies[0] == "T-999"
        assert isinstance(read_back.dependencies[1], Dependency)
        assert read_back.dependencies[1].type == DependencyType.WAITS_FOR


class TestManifestWithTypedDeps:
    def test_manifest_stores_blocking_deps_for_met_check(self, tmp_path: Path) -> None:
        """Manifest deps_met check should only consider blocking types."""
        repo = LocalTaskRepository(tmp_path)
        dep_detail = repo.create_task(_make_task(title="Dep task"))

        main_detail = repo.create_task(
            _make_task(
                title="Main task",
                dependencies=[dep_detail.id],
            )
        )

        tasks = repo.list_tasks(state="open")
        main = next(t for t in tasks if t.id == main_detail.id)
        assert main.dependencies_met is False

        repo.update_status(dep_detail.id, "done")
        tasks = repo.list_tasks(state="all")
        main = next(t for t in tasks if t.id == main_detail.id)
        assert main.dependencies_met is True

    def test_manifest_ignores_nonblocking_deps_for_met_check(self, tmp_path: Path) -> None:
        """Non-blocking deps should not affect dependencies_met."""
        repo = LocalTaskRepository(tmp_path)
        dep_detail = repo.create_task(_make_task(title="Dep task"))

        validates_dep = Dependency(task_id=dep_detail.id, type=DependencyType.VALIDATES)
        main_detail = repo.create_task(
            _make_task(
                title="Test task",
                dependencies=[validates_dep],
            )
        )

        tasks = repo.list_tasks(state="open")
        test_task = next(t for t in tasks if t.id == main_detail.id)
        assert test_task.dependencies_met is True

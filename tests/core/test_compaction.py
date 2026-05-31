"""Tests for task compaction -- TDD: tests written before implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from odk.core.compaction import TaskCompactor
from odk.models.compaction import CompactedTask
from odk.models.pm import AcceptanceCriterion, TaskCreate, TaskDetail
from odk.repositories.local.frontmatter import parse_frontmatter
from odk.repositories.local.tasks import LocalTaskRepository

if TYPE_CHECKING:
    from pathlib import Path


def _make_done_task(
    repo: LocalTaskRepository,
    *,
    title: str = "Implement order validation",
    description: str = "Validate all incoming orders against rules.",
) -> TaskDetail:
    """Create a task and mark it done so it is compactable."""
    detail = repo.create_task(
        TaskCreate(
            title=title,
            story_id="S-001",
            description=description,
            acceptance_criteria=[
                AcceptanceCriterion(text="Orders with invalid symbol rejected"),
                AcceptanceCriterion(text="Balance check passes"),
            ],
            test_strategy="Unit tests for validation",
        )
    )
    repo.update_status(detail.id, "done")
    repo.add_comment(detail.id, "Started implementation.")
    repo.add_comment(detail.id, "Decided to use strategy pattern for validators.")
    repo.add_comment(detail.id, "All tests passing. PR merged.")
    return repo.get_task(detail.id)


class TestIsCompactable:
    def test_done_task_is_compactable(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        task = _make_done_task(repo)
        compactor = TaskCompactor()
        assert compactor.is_compactable(task) is True

    def test_closed_task_is_compactable(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        detail = repo.create_task(
            TaskCreate(
                title="Old task",
                story_id="S-001",
                description="Legacy.",
            ),
        )
        repo.update_status(detail.id, "closed")
        task = repo.get_task(detail.id)
        compactor = TaskCompactor()
        assert compactor.is_compactable(task) is True

    def test_open_task_not_compactable(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        detail = repo.create_task(
            TaskCreate(
                title="WIP task",
                story_id="S-001",
                description="Still working.",
            ),
        )
        task = repo.get_task(detail.id)
        compactor = TaskCompactor()
        assert compactor.is_compactable(task) is False

    def test_in_progress_task_not_compactable(
        self,
        tmp_path: Path,
    ) -> None:
        repo = LocalTaskRepository(tmp_path)
        detail = repo.create_task(
            TaskCreate(
                title="Active task",
                story_id="S-001",
                description="In progress.",
            ),
        )
        repo.update_status(detail.id, "in-progress")
        task = repo.get_task(detail.id)
        compactor = TaskCompactor()
        assert compactor.is_compactable(task) is False


class TestCompactTaskDeterministic:
    """Test deterministic fallback compaction (no LLM)."""

    def test_preserves_essential_fields(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        task = _make_done_task(repo)
        compactor = TaskCompactor()
        result = compactor.compact_task(task)

        assert isinstance(result, CompactedTask)
        assert result.id == task.id
        assert result.title == task.title
        assert result.status == "done"
        assert result.original_description == task.description
        assert result.compacted_at != ""

    def test_summary_is_nonempty(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        task = _make_done_task(repo)
        compactor = TaskCompactor()
        result = compactor.compact_task(task)
        assert len(result.summary) > 0

    def test_rejects_non_done_task(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        detail = repo.create_task(
            TaskCreate(
                title="Open task",
                story_id="S-001",
                description="Not done.",
            ),
        )
        task = repo.get_task(detail.id)
        compactor = TaskCompactor()
        with pytest.raises(ValueError, match=r"(?i)compactable"):
            compactor.compact_task(task)

    def test_key_decisions_is_list(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        task = _make_done_task(repo)
        compactor = TaskCompactor()
        result = compactor.compact_task(task)
        assert isinstance(result.key_decisions, list)

    def test_files_modified_is_list(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        task = _make_done_task(repo)
        compactor = TaskCompactor()
        result = compactor.compact_task(task)
        assert isinstance(result.files_modified, list)


class TestCompactTasksBatch:
    def test_compact_multiple_tasks(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        t1 = _make_done_task(repo, title="Task A", description="First task.")
        t2 = _make_done_task(repo, title="Task B", description="Second task.")
        compactor = TaskCompactor()
        results = compactor.compact_tasks([t1, t2])
        assert len(results) == 2
        assert results[0].title == "Task A"
        assert results[1].title == "Task B"


class TestLLMSummarization:
    """Test LLM summarization path with a mock provider."""

    def test_uses_llm_when_provided(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        task = _make_done_task(repo)

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = (
            '{"summary": "Implemented order validation using strategy'
            ' pattern.",'
            ' "key_decisions": ["Used strategy pattern for'
            ' extensibility"],'
            ' "files_modified": ["src/orders/validator.py"]}'
        )

        compactor = TaskCompactor(llm_provider=mock_llm)
        result = compactor.compact_task(task)

        assert mock_llm.invoke.called
        assert "strategy pattern" in result.summary
        assert len(result.key_decisions) == 1
        assert "src/orders/validator.py" in result.files_modified

    def test_falls_back_on_llm_parse_failure(
        self,
        tmp_path: Path,
    ) -> None:
        repo = LocalTaskRepository(tmp_path)
        task = _make_done_task(repo)

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = "not valid json at all"

        compactor = TaskCompactor(llm_provider=mock_llm)
        result = compactor.compact_task(task)

        assert isinstance(result, CompactedTask)
        assert result.id == task.id
        assert len(result.summary) > 0


class TestRepositoryCompaction:
    """Test compact_task on LocalTaskRepository -- file replacement."""

    def test_compact_replaces_file(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        task = _make_done_task(repo)
        repo.compact_task(task.id)

        file_path = tmp_path / "tasks" / f"{task.id}.md"
        content = file_path.read_text(encoding="utf-8")
        fm, _body = parse_frontmatter(content)
        assert fm.get("compacted") is True

    def test_compact_preserves_manifest(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        task = _make_done_task(repo)
        repo.compact_task(task.id)

        from odk.repositories.local.manifest import Manifest

        data = Manifest(tmp_path).load()
        assert task.id in data["tasks"]
        assert data["tasks"][task.id].get("compacted") is True

    def test_compact_all_done(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        t1 = _make_done_task(repo, title="Done A")
        _open = repo.create_task(
            TaskCreate(
                title="Still open",
                story_id="S-001",
                description="WIP.",
            ),
        )
        t2 = _make_done_task(repo, title="Done B")

        compacted_ids = repo.compact_all_done()
        assert set(compacted_ids) == {t1.id, t2.id}

        open_task = repo.get_task(_open.id)
        assert open_task.status == "open"

    def test_dry_run_does_not_modify(self, tmp_path: Path) -> None:
        repo = LocalTaskRepository(tmp_path)
        task = _make_done_task(repo)
        file_path = tmp_path / "tasks" / f"{task.id}.md"
        content_before = file_path.read_text(encoding="utf-8")

        compacted_ids = repo.compact_all_done(dry_run=True)
        assert task.id in compacted_ids

        content_after = file_path.read_text(encoding="utf-8")
        assert content_before == content_after

    def test_compacted_flag_in_frontmatter(
        self,
        tmp_path: Path,
    ) -> None:
        repo = LocalTaskRepository(tmp_path)
        task = _make_done_task(repo)
        repo.compact_task(task.id)

        file_path = tmp_path / "tasks" / f"{task.id}.md"
        fm, _body = parse_frontmatter(file_path.read_text(encoding="utf-8"))
        assert fm["compacted"] is True
        assert fm["status"] == "done"

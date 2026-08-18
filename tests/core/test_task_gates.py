"""Tests for gate integration in task lifecycle and repository."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ydk.core.events import EventBus
from ydk.core.task_lifecycle import TaskLifecycle
from ydk.models.gate import Gate, GateStatus, GateType
from ydk.models.pm import AcceptanceCriterion, TaskCreate, TaskDetail
from ydk.repositories.local.frontmatter import parse_frontmatter
from ydk.repositories.local.tasks import LocalTaskRepository


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock()
    repo.get_task.return_value = TaskDetail(
        id="T-001",
        title="Test task",
        story_id="S-001",
        status="open",
        gates=[Gate(id="G-001", type=GateType.HUMAN, description="Approval", status=GateStatus.RESOLVED)],
    )
    repo.check_dependencies.return_value = []
    return repo


@pytest.fixture
def lifecycle(mock_repo) -> TaskLifecycle:
    events = EventBus()
    wt = MagicMock()
    wt.create.return_value = Path("/tmp/worktree/T-001")
    verifier = MagicMock()
    return TaskLifecycle(
        repo=mock_repo, events=events, worktree_mgr=wt, verifier=verifier, project_root=Path("/tmp/project")
    )


class TestTaskStartBlockedByGate:
    def test_start_allowed_when_all_gates_resolved(self, lifecycle) -> None:
        result = lifecycle.start("T-001")
        assert "task" in result

    def test_start_blocked_by_pending_gate(self, lifecycle, mock_repo) -> None:
        mock_repo.get_task.return_value = TaskDetail(
            id="T-001",
            title="Test task",
            status="open",
            gates=[Gate(id="G-001", type=GateType.HUMAN, description="Waiting approval")],
        )
        with pytest.raises(ValueError, match="Unresolved gates"):
            lifecycle.start("T-001")

    def test_start_blocked_by_failed_gate(self, lifecycle, mock_repo) -> None:
        mock_repo.get_task.return_value = TaskDetail(
            id="T-001",
            title="Test task",
            status="open",
            gates=[Gate(id="G-001", type=GateType.CI_PASSED, description="CI failed", status=GateStatus.FAILED)],
        )
        with pytest.raises(ValueError, match="Unresolved gates"):
            lifecycle.start("T-001")

    def test_start_allowed_with_no_gates(self, lifecycle, mock_repo) -> None:
        mock_repo.get_task.return_value = TaskDetail(id="T-001", title="Test task", status="open", gates=[])
        result = lifecycle.start("T-001")
        assert "task" in result

    def test_start_blocked_when_one_of_many_gates_pending(self, lifecycle, mock_repo) -> None:
        mock_repo.get_task.return_value = TaskDetail(
            id="T-001",
            title="Test task",
            status="open",
            gates=[
                Gate(id="G-001", type=GateType.HUMAN, description="Approved", status=GateStatus.RESOLVED),
                Gate(id="G-002", type=GateType.PR_MERGED, description="PR pending"),
            ],
        )
        with pytest.raises(ValueError, match="Unresolved gates"):
            lifecycle.start("T-001")


def _make_task(**overrides):
    defaults = {
        "title": "Gated task",
        "story_id": "S-001",
        "spec_refs": [],
        "dependencies": [],
        "description": "A task with gates.",
        "acceptance_criteria": [AcceptanceCriterion(text="It works")],
        "test_strategy": "Unit tests",
    }
    defaults.update(overrides)
    return TaskCreate(**defaults)


class TestGateSerializationInFrontmatter:
    def test_create_task_with_gates_persists_to_file(self, tmp_path) -> None:
        repo = LocalTaskRepository(tmp_path)
        gates = [
            Gate(id="G-001", type=GateType.PR_MERGED, description="Wait for PR", config={"pr_url": "https://x/1"}),
            Gate(id="G-002", type=GateType.HUMAN, description="Approval"),
        ]
        detail = repo.create_task(_make_task(gates=gates))
        file_path = tmp_path / "tasks" / f"{detail.id}.md"
        fm, _body = parse_frontmatter(file_path.read_text(encoding="utf-8"))
        assert "gates" in fm
        assert len(fm["gates"]) == 2
        assert fm["gates"][0]["id"] == "G-001"

    def test_get_task_with_gates_roundtrips(self, tmp_path) -> None:
        repo = LocalTaskRepository(tmp_path)
        gates = [
            Gate(
                id="G-001",
                type=GateType.CI_PASSED,
                description="CI",
                config={"run_url": "https://x/runs/1"},
                status=GateStatus.RESOLVED,
                resolved_at="2025-06-01T12:00:00Z",
            )
        ]
        created = repo.create_task(_make_task(gates=gates))
        detail = repo.get_task(created.id)
        assert len(detail.gates) == 1
        g = detail.gates[0]
        assert isinstance(g, Gate)
        assert g.id == "G-001"
        assert g.type == GateType.CI_PASSED
        assert g.status == GateStatus.RESOLVED

    def test_create_task_without_gates_has_empty_list(self, tmp_path) -> None:
        repo = LocalTaskRepository(tmp_path)
        detail = repo.create_task(_make_task())
        reloaded = repo.get_task(detail.id)
        assert reloaded.gates == []

    def test_gates_in_manifest(self, tmp_path) -> None:
        from ydk.repositories.local.manifest import Manifest

        repo = LocalTaskRepository(tmp_path)
        gates = [Gate(id="G-001", type=GateType.HUMAN, description="Approval")]
        detail = repo.create_task(_make_task(gates=gates))
        data = Manifest(tmp_path).load()
        task_entry = data["tasks"][detail.id]
        assert "gates" in task_entry
        assert len(task_entry["gates"]) == 1

"""Tests for ydk memory commands."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ydk.cli import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _mock_engine():
    """Create a mock MemoryEngine."""
    engine = MagicMock()
    engine.index_all.return_value = {"files": 12, "chunks": 48, "skipped": 2}
    engine.search.return_value = [
        {"source": "docs/specs/orders.md", "section": "Entities", "score": 0.92, "snippet": "Order entity has..."},
    ]
    engine.bootstrap.return_value = [
        {"type": "spec", "source": "docs/specs/orders.md", "snippet": "Order validation rules..."},
    ]
    engine.store.return_value = None
    return engine


def _mock_extractor():
    """Create a mock MemoryExtractor."""
    from ydk.core.extractor import ExtractedMemory

    extractor = MagicMock()
    extractor.extract_from_jsonl.return_value = [
        ExtractedMemory(memory_type="gotcha", content="Binance returns 418 for IP bans"),
    ]
    return extractor


def _mock_task():
    """Create a mock task object."""
    task = MagicMock()
    task.id = "T-001"
    task.title = "Test task"
    task.description = "A test task description"
    task.spec_refs = ["docs/specs/orders.md"]
    return task


@patch("ydk.cli.memory_cmd._get_engine")
@patch("ydk.cli.memory_cmd._load_memory_config")
def test_memory_index(mock_config: MagicMock, mock_get_engine: MagicMock) -> None:
    """ydk memory index exits 0 with mock MemoryEngine."""
    mock_get_engine.return_value = _mock_engine()
    result = runner.invoke(app, ["memory", "index"])
    assert result.exit_code == 0
    assert "Indexed 12 files" in result.output


@patch("ydk.cli.memory_cmd._get_engine")
@patch("ydk.cli.memory_cmd._load_memory_config")
def test_memory_search(mock_config: MagicMock, mock_get_engine: MagicMock) -> None:
    """ydk memory search exits 0 with mock search results."""
    mock_get_engine.return_value = _mock_engine()
    result = runner.invoke(app, ["memory", "search", "order validation"])
    assert result.exit_code == 0
    assert "orders.md" in result.output


@patch("ydk.repositories.factory.get_task_repository")
@patch("ydk.cli.memory_cmd._get_engine")
@patch("ydk.cli.memory_cmd._load_memory_config")
def test_memory_bootstrap(mock_config: MagicMock, mock_get_engine: MagicMock, mock_repo_factory: MagicMock) -> None:
    """ydk memory bootstrap T-001 exits 0 with mock bootstrap results."""
    mock_get_engine.return_value = _mock_engine()
    mock_repo = MagicMock()
    mock_repo.get_task.return_value = _mock_task()
    mock_repo_factory.return_value = mock_repo
    result = runner.invoke(app, ["memory", "bootstrap", "T-001"])
    assert result.exit_code == 0
    assert "Bootstrap context for T-001" in result.output


@patch("ydk.cli.memory_cmd._get_extractor")
@patch("ydk.cli.memory_cmd._get_engine")
@patch("ydk.cli.memory_cmd._load_memory_config")
def test_memory_extract(
    mock_config: MagicMock, mock_get_engine: MagicMock, mock_get_extractor: MagicMock, tmp_path: Path
) -> None:
    """ydk memory extract T-001 --jsonl file.jsonl exits 0 with mock extractor."""
    mock_get_engine.return_value = _mock_engine()
    mock_get_extractor.return_value = _mock_extractor()
    jsonl_file = tmp_path / "session.jsonl"
    jsonl_file.write_text('{"role": "user", "content": "hello"}\n')
    result = runner.invoke(app, ["memory", "extract", "T-001", "--jsonl", str(jsonl_file)])
    assert result.exit_code == 0
    assert "Extracted 1 memories" in result.output


@patch("ydk.cli.memory_cmd._get_engine")
@patch("ydk.cli.memory_cmd._load_memory_config")
def test_memory_search_shows_provenance(mock_config: MagicMock, mock_get_engine: MagicMock) -> None:
    """ydk memory search displays source_type and verified status."""
    engine = _mock_engine()
    engine.search.return_value = [
        {
            "source": "docs/specs/orders.md",
            "section": "Entities",
            "score": 0.92,
            "snippet": "Order entity has...",
            "source_type": "llm-extracted",
            "verified": False,
        },
    ]
    mock_get_engine.return_value = engine
    result = runner.invoke(app, ["memory", "search", "order validation"])
    assert result.exit_code == 0
    assert "llm-extracted" in result.output


@patch("ydk.cli.memory_cmd._get_engine")
@patch("ydk.cli.memory_cmd._load_memory_config")
def test_memory_search_verified_only(mock_config: MagicMock, mock_get_engine: MagicMock) -> None:
    """ydk memory search --verified-only filters to verified results."""
    engine = _mock_engine()
    engine.search.return_value = [
        {
            "source": "docs/specs/orders.md",
            "section": "Entities",
            "score": 0.92,
            "snippet": "Order entity has...",
            "source_type": "user-stated",
            "verified": True,
        },
        {
            "source": "docs/specs/auth.md",
            "section": "Tokens",
            "score": 0.85,
            "snippet": "JWT tokens...",
            "source_type": "llm-extracted",
            "verified": False,
        },
    ]
    mock_get_engine.return_value = engine
    result = runner.invoke(app, ["memory", "search", "--verified-only", "order validation"])
    assert result.exit_code == 0
    assert "orders.md" in result.output
    assert "auth.md" not in result.output


@patch("ydk.cli.memory_cmd._load_memory_config")
def test_memory_audit(mock_config: MagicMock) -> None:
    """ydk memory audit exits 0."""
    cfg = MagicMock()
    cfg.project.research_location = "/tmp/nonexistent_research_dir_ydk"
    mock_config.return_value = cfg
    result = runner.invoke(app, ["memory", "audit"])
    assert result.exit_code == 0
    assert "Memory Audit" in result.output


@patch("ydk.repositories.factory.get_task_repository")
def test_memory_retrospective(mock_repo_factory: MagicMock) -> None:
    """ydk memory retrospective exits 0."""
    mock_repo = MagicMock()
    task = MagicMock()
    task.id = "T-001"
    task.title = "Completed task"
    task.status = "done"
    task.milestone = None
    mock_repo.list_tasks.return_value = [task]
    mock_repo_factory.return_value = mock_repo
    result = runner.invoke(app, ["memory", "retrospective"])
    assert result.exit_code == 0
    assert "Sprint Retrospective" in result.output

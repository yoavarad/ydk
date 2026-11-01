"""Tests for ydk memory commands."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ydk.cli import app

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from click.testing import Result

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
def test_memory_retrospective(mock_repo_factory: MagicMock, tmp_path: Path, monkeypatch: object) -> None:
    """ydk memory retrospective exits 0."""
    from types import SimpleNamespace

    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    import json

    client = MagicMock()
    client.messages.parse.side_effect = lambda **kw: SimpleNamespace(
        stop_reason="end_turn",
        parsed_output=kw["output_format"].model_validate(
            {"patterns": ["p"], "templates": ["t"], "rules": ["r"], "summary": "s"}
        ),
    )
    mock_repo = MagicMock()
    task = MagicMock()
    task.id = "T-001"
    task.title = "Completed task"
    task.status = "done"
    task.milestone = None
    mock_repo.list_tasks.return_value = [task]
    mock_repo_factory.return_value = mock_repo
    with patch("anthropic.Anthropic", return_value=client):
        result = runner.invoke(app, ["memory", "retrospective"])
    assert result.exit_code == 0
    assert "Sprint Retrospective" in result.output
    assert "Pattern: p" in result.output

    call = client.messages.parse.call_args[1]
    assert "temperature" not in call
    assert "tool_choice" not in call
    saved = json.loads((tmp_path / ".ydk" / "proofs" / "retrospective-current.json").read_text())
    assert saved == {"patterns": ["p"], "templates": ["t"], "rules": ["r"], "summary": "s"}


def test_memory_retrospective_rejects_both_sprint_and_epic() -> None:
    """--sprint and --epic together is a usage error."""
    result = runner.invoke(app, ["memory", "retrospective", "--sprint", "1", "--epic", "E-001"])
    assert result.exit_code == 1


@patch("ydk.repositories.factory.get_epic_repository")
@patch("ydk.repositories.factory.get_story_repository")
@patch("ydk.repositories.factory.get_task_repository")
def test_memory_retrospective_epic(
    mock_task_repo_factory: MagicMock,
    mock_story_repo_factory: MagicMock,
    mock_epic_repo_factory: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ydk memory retrospective --epic gathers the epic's tasks, writes a markdown
    retro file, and marks the epic retro-done.

    Uses real local repositories (not mocks of internal classes) sharing one
    ``.ydk`` root, wired in via the factory functions -- only the factory
    seam is patched.
    """
    from types import SimpleNamespace

    from ydk.models.pm import EpicCreate, StoryCreate, TaskCreate
    from ydk.repositories.local.epics import LocalEpicRepository
    from ydk.repositories.local.stories import LocalStoryRepository
    from ydk.repositories.local.tasks import LocalTaskRepository

    monkeypatch.chdir(tmp_path)
    root = tmp_path / ".ydk"
    task_repo = LocalTaskRepository(root)
    story_repo = LocalStoryRepository(root)
    epic_repo = LocalEpicRepository(root)

    epic_id = epic_repo.create_epic(EpicCreate(title="Ship it")).id
    story_id = story_repo.create_story(StoryCreate(title="Story one", epic_id=epic_id)).id
    task_id = task_repo.create_task(TaskCreate(title="Completed task", story_id=story_id)).id
    task_repo.update_status(task_id, "done")

    mock_task_repo_factory.return_value = task_repo
    mock_story_repo_factory.return_value = story_repo
    mock_epic_repo_factory.return_value = epic_repo

    client = MagicMock()
    client.messages.parse.side_effect = lambda **kw: SimpleNamespace(
        stop_reason="end_turn",
        parsed_output=kw["output_format"].model_validate(
            {"patterns": ["p"], "templates": ["t"], "rules": ["r"], "summary": "s"}
        ),
    )
    with patch("anthropic.Anthropic", return_value=client):
        result = runner.invoke(app, ["memory", "retrospective", "--epic", epic_id])

    assert result.exit_code == 0
    assert "Epic Retrospective" in result.output
    retro_file = tmp_path / ".ydk" / "retros" / f"{epic_id}.md"
    assert retro_file.is_file()
    assert task_id in retro_file.read_text(encoding="utf-8")
    epic_content = (root / "epics" / f"{epic_id}.md").read_text(encoding="utf-8")
    assert f"retro: .ydk/retros/{epic_id}.md" in epic_content


@patch("ydk.repositories.factory.get_story_repository")
@patch("ydk.repositories.factory.get_task_repository")
def test_memory_retrospective_epic_no_tasks(
    mock_task_repo_factory: MagicMock,
    mock_story_repo_factory: MagicMock,
    tmp_path: Path,
) -> None:
    """ydk memory retrospective --epic with no done tasks prints the empty message."""
    from ydk.repositories.local.stories import LocalStoryRepository
    from ydk.repositories.local.tasks import LocalTaskRepository

    root = tmp_path / ".ydk"
    mock_task_repo_factory.return_value = LocalTaskRepository(root)
    mock_story_repo_factory.return_value = LocalStoryRepository(root)

    result = runner.invoke(app, ["memory", "retrospective", "--epic", "E-404"])
    assert result.exit_code == 0
    assert "No completed tasks found for retrospective." in result.output


# ---------------------------------------------------------------------------
# Claude API failures surface clearly (mock only the anthropic SDK boundary)
# ---------------------------------------------------------------------------


def _auth_failing_client() -> MagicMock:
    import anthropic
    import httpx

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client = MagicMock()
    error = anthropic.AuthenticationError("bad key", response=httpx.Response(401, request=request), body=None)
    client.messages.create.side_effect = error
    client.messages.parse.side_effect = error
    return client


def _closed_task_repo() -> MagicMock:
    repo = MagicMock()
    task = MagicMock()
    task.id = "T-001"
    task.title = "Completed task"
    task.status = "done"
    task.milestone = None
    repo.list_tasks.return_value = [task]
    return repo


@patch("ydk.cli.memory_cmd._get_engine")
def test_memory_extract_authentication_error_is_clear(
    mock_get_engine: MagicMock, tmp_path: Path, monkeypatch: object
) -> None:
    import json

    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    mock_get_engine.return_value = _mock_engine()
    jsonl_file = tmp_path / "session.jsonl"
    jsonl_file.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": "Fix the bug"}}) + "\n")

    with patch("anthropic.Anthropic", return_value=_auth_failing_client()):
        result = runner.invoke(app, ["memory", "extract", "T-001", "--jsonl", str(jsonl_file)])

    assert result.exit_code == 1
    assert "invalid or missing API key" in result.output
    assert isinstance(result.exception, SystemExit)


@patch("ydk.repositories.factory.get_task_repository")
def test_memory_retrospective_authentication_error_is_clear(
    mock_repo_factory: MagicMock, tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    mock_repo_factory.return_value = _closed_task_repo()

    with patch("anthropic.Anthropic", return_value=_auth_failing_client()):
        result = runner.invoke(app, ["memory", "retrospective"])

    assert result.exit_code == 1
    assert "invalid or missing API key" in result.output
    assert isinstance(result.exception, SystemExit)


@patch("ydk.repositories.factory.get_task_repository")
def test_memory_retrospective_missing_credentials_reported(
    mock_repo_factory: MagicMock, tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    (tmp_path / ".ydk").mkdir()
    (tmp_path / ".ydk" / "config.yaml").write_text(
        "project:\n  name: t\nanthropic:\n  api_key_env: YDK_TEST_MISSING_KEY\n", encoding="utf-8"
    )
    monkeypatch.delenv("YDK_TEST_MISSING_KEY", raising=False)  # type: ignore[attr-defined]
    mock_repo_factory.return_value = _closed_task_repo()

    with patch("anthropic.Anthropic") as mock_cls:
        result = runner.invoke(app, ["memory", "retrospective"])

    assert result.exit_code == 1
    assert "YDK_TEST_MISSING_KEY" in result.output
    mock_cls.assert_not_called()


def _missing_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Local epic repo with one done epic, one open epic; returns (repo, done_id, open_id)."""
    from ydk.models.pm import EpicCreate
    from ydk.repositories.local.epics import LocalEpicRepository

    monkeypatch.chdir(tmp_path)
    repo = LocalEpicRepository(tmp_path / ".ydk")
    done_id = repo.create_epic(EpicCreate(title="Finished epic")).id
    open_id = repo.create_epic(EpicCreate(title="Open epic")).id
    repo.update_status(done_id, "done")
    return repo, done_id, open_id


@patch("ydk.repositories.factory.get_epic_repository")
def test_memory_retrospective_missing_lists_tsv(
    mock_epic_factory: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, done_id, open_id = _missing_setup(tmp_path, monkeypatch)
    mock_epic_factory.return_value = repo
    result = runner.invoke(app, ["memory", "retrospective", "--missing"])
    assert result.exit_code == 0
    assert f"{done_id}\tFinished epic" in result.output
    assert open_id not in result.output
    assert not (tmp_path / ".ydk" / "retros").exists()


@patch("ydk.repositories.factory.get_epic_repository")
def test_memory_retrospective_missing_json(
    mock_epic_factory: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, done_id, _ = _missing_setup(tmp_path, monkeypatch)
    mock_epic_factory.return_value = repo
    result = runner.invoke(app, ["memory", "retrospective", "--missing", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == [{"epic_id": done_id, "title": "Finished epic"}]


@patch("ydk.repositories.factory.get_epic_repository")
def test_memory_retrospective_missing_retro_file_excludes_epic(
    mock_epic_factory: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, done_id, _ = _missing_setup(tmp_path, monkeypatch)
    mock_epic_factory.return_value = repo
    (tmp_path / ".ydk" / "retros").mkdir(parents=True)
    (tmp_path / ".ydk" / "retros" / f"{done_id}.md").write_text("x", encoding="utf-8")
    text = runner.invoke(app, ["memory", "retrospective", "--missing"])
    assert text.exit_code == 0
    assert "No epics missing a retrospective." in text.output
    as_json = runner.invoke(app, ["memory", "retrospective", "--missing", "--json"])
    assert as_json.exit_code == 0
    assert json.loads(as_json.output) == []


@patch("ydk.repositories.factory.get_epic_repository")
def test_memory_retrospective_missing_ignores_require_epic_retro_config(
    mock_epic_factory: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, done_id, _ = _missing_setup(tmp_path, monkeypatch)
    mock_epic_factory.return_value = repo
    (tmp_path / ".ydk" / "config.yaml").write_text("learning:\n  require_epic_retro: false\n", encoding="utf-8")
    result = runner.invoke(app, ["memory", "retrospective", "--missing"])
    assert result.exit_code == 0
    assert done_id in result.output


def test_memory_retrospective_missing_conflicts_exit_1() -> None:
    for extra in (["--epic", "E-1"], ["--sprint", "1"]):
        result = runner.invoke(app, ["memory", "retrospective", "--missing", *extra])
        assert result.exit_code == 1


def test_memory_retrospective_json_requires_missing() -> None:
    result = runner.invoke(app, ["memory", "retrospective", "--json"])
    assert result.exit_code == 1


def test_memory_retrospective_missing_backend_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> None:
        raise RuntimeError("backend down")

    monkeypatch.setattr("ydk.repositories.factory.get_epic_repository", boom)
    result = runner.invoke(app, ["memory", "retrospective", "--missing"])
    assert result.exit_code == 1
    assert "backend down" in result.output


def _run_epic_retro(tmp_path: Path, epic_repo: object, epic_id: str) -> object:
    """Invoke `memory retrospective --epic` with real local repos; only factories and LLM mocked."""
    from types import SimpleNamespace

    from ydk.models.pm import StoryCreate, TaskCreate
    from ydk.repositories.local.stories import LocalStoryRepository
    from ydk.repositories.local.tasks import LocalTaskRepository

    root = tmp_path / ".ydk"
    task_repo = LocalTaskRepository(root)
    story_repo = LocalStoryRepository(root)
    story_id = story_repo.create_story(StoryCreate(title="S", epic_id=epic_id)).id
    task_id = task_repo.create_task(TaskCreate(title="Done task", story_id=story_id)).id
    task_repo.update_status(task_id, "done")
    client = MagicMock()
    client.messages.parse.side_effect = lambda **kw: SimpleNamespace(
        stop_reason="end_turn",
        parsed_output=kw["output_format"].model_validate(
            {"patterns": ["p"], "templates": ["t"], "rules": ["r"], "summary": "s"}
        ),
    )
    with (
        patch("ydk.repositories.factory.get_task_repository", return_value=task_repo),
        patch("ydk.repositories.factory.get_story_repository", return_value=story_repo),
        patch("ydk.repositories.factory.get_epic_repository", return_value=epic_repo),
        patch("anthropic.Anthropic", return_value=client),
    ):
        return runner.invoke(app, ["memory", "retrospective", "--epic", epic_id])


def test_memory_retrospective_epic_writes_frontmatter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ydk.models.pm import EpicCreate
    from ydk.repositories.local.epics import LocalEpicRepository

    monkeypatch.chdir(tmp_path)
    epic_repo = LocalEpicRepository(tmp_path / ".ydk")
    epic_id = epic_repo.create_epic(EpicCreate(title="Ship it")).id
    result = _run_epic_retro(tmp_path, epic_repo, epic_id)
    assert result.exit_code == 0  # type: ignore[attr-defined]
    text = (tmp_path / ".ydk" / "retros" / f"{epic_id}.md").read_text(encoding="utf-8")
    assert text.startswith(f'---\nepic_id: "{epic_id}"\ntitle: "Ship it"\nurl: ""\n---\n')


def test_memory_retrospective_epic_collision_and_rerun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ydk.models.pm import EpicCreate
    from ydk.repositories.local.epics import LocalEpicRepository

    monkeypatch.chdir(tmp_path)
    epic_repo = LocalEpicRepository(tmp_path / ".ydk")
    epic_id = epic_repo.create_epic(EpicCreate(title="New Epic")).id
    retros = tmp_path / ".ydk" / "retros"
    retros.mkdir(parents=True)
    old = f'---\nepic_id: "{epic_id}"\ntitle: "Old Epic"\nurl: ""\n---\n\n# old\n'
    (retros / f"{epic_id}.md").write_bytes(old.encode())

    for _ in range(2):
        result = _run_epic_retro(tmp_path, epic_repo, epic_id)
        assert result.exit_code == 0  # type: ignore[attr-defined]

    assert (retros / f"{epic_id}.md").read_bytes() == old.encode()
    assert sorted(p.name for p in retros.iterdir()) == sorted([f"{epic_id}.md", f"{epic_id}-new-epic.md"])


def test_memory_retrospective_missing_json_reports_reused_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ydk.models.pm import EpicCreate
    from ydk.repositories.local.epics import LocalEpicRepository

    monkeypatch.chdir(tmp_path)
    repo = LocalEpicRepository(tmp_path / ".ydk")
    epic_id = repo.create_epic(EpicCreate(title="New Epic")).id
    repo.update_status(epic_id, "done")
    retros = tmp_path / ".ydk" / "retros"
    retros.mkdir(parents=True)
    (retros / f"{epic_id}.md").write_text(
        f'---\nepic_id: "{epic_id}"\ntitle: "Old Epic"\nurl: ""\n---\n', encoding="utf-8"
    )
    with patch("ydk.repositories.factory.get_epic_repository", return_value=repo):
        result = runner.invoke(app, ["memory", "retrospective", "--missing", "--json"])
    assert json.loads(result.output) == [{"epic_id": epic_id, "title": "New Epic"}]


# ---------------------------------------------------------------------------
# Subagent handoff route (no API key): exit 3 with request block, then rerun
# ---------------------------------------------------------------------------


def _write_subagent_config(root: Path, purpose: str) -> None:
    """Route ``purpose`` to the subagent provider; the API key env var is deliberately unset."""
    (root / ".ydk").mkdir(exist_ok=True)
    (root / ".ydk" / "config.yaml").write_text(
        "project:\n  name: t\nanthropic:\n  api_key_env: YDK_TEST_MISSING_KEY\n"
        f"ai:\n  routes:\n    {purpose}: subagent\n",
        encoding="utf-8",
    )


def _answer_requests(output: str, purpose: str, answer: dict) -> int:
    """Write ``answer`` as the response for every request listed in the handoff block."""
    from pathlib import Path

    lines = output.splitlines()
    start = lines.index("YDK-SUBAGENT-REQUESTS:")
    paths = [Path(ln[2:]) for ln in lines[start + 1 :] if ln.startswith("- ")]
    for p in paths:
        assert json.loads(p.read_text(encoding="utf-8"))["purpose"] == purpose
        responses = p.parent.parent / "responses"
        responses.mkdir(parents=True, exist_ok=True)
        (responses / p.name).write_text(json.dumps(answer), encoding="utf-8")
    return len(paths)


@patch("ydk.cli.memory_cmd._get_engine")
def test_memory_extract_subagent_handoff_then_rerun(
    mock_get_engine: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YDK_TEST_MISSING_KEY", raising=False)
    _write_subagent_config(tmp_path, "extract")
    engine = _mock_engine()
    mock_get_engine.return_value = engine
    jsonl_file = tmp_path / "session.jsonl"
    jsonl_file.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": "Fix the bug"}}) + "\n")
    args = ["memory", "extract", "T-001", "--jsonl", str(jsonl_file)]

    first = runner.invoke(app, args)

    assert first.exit_code == 3, first.output
    assert "Rerun this command after writing responses." in first.output
    engine.add_extraction.assert_not_called()
    memory = {
        "memory_type": "gotcha",
        "content": "Retry on 418",
        "related_files": [],
        "concepts": [],
        "importance": "high",
    }
    assert _answer_requests(first.output, "extract", {"memories": [memory]}) == 1

    second = runner.invoke(app, args)

    assert second.exit_code == 0, second.output
    assert "Extracted 1 memories" in second.output
    engine.add_extraction.assert_called_once()


def test_memory_retrospective_epic_subagent_handoff_satisfies_retro_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path

    from ydk.core.retro_gate import find_epics_missing_retro
    from ydk.models.pm import EpicCreate, StoryCreate, TaskCreate
    from ydk.repositories.local.epics import LocalEpicRepository
    from ydk.repositories.local.stories import LocalStoryRepository
    from ydk.repositories.local.tasks import LocalTaskRepository

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YDK_TEST_MISSING_KEY", raising=False)
    _write_subagent_config(tmp_path, "retrospective")
    root = tmp_path / ".ydk"
    task_repo = LocalTaskRepository(root)
    story_repo = LocalStoryRepository(root)
    epic_repo = LocalEpicRepository(root)
    epic_id = epic_repo.create_epic(EpicCreate(title="Ship it")).id
    story_id = story_repo.create_story(StoryCreate(title="S", epic_id=epic_id)).id
    task_id = task_repo.create_task(TaskCreate(title="Done task", story_id=story_id)).id
    task_repo.update_status(task_id, "done")
    epic_repo.update_status(epic_id, "done")
    retros = Path(".ydk/retros")

    def run() -> Result:
        with (
            patch("ydk.repositories.factory.get_task_repository", return_value=task_repo),
            patch("ydk.repositories.factory.get_story_repository", return_value=story_repo),
            patch("ydk.repositories.factory.get_epic_repository", return_value=epic_repo),
        ):
            return runner.invoke(app, ["memory", "retrospective", "--epic", epic_id])

    first = run()

    assert first.exit_code == 3, first.output
    assert not (tmp_path / ".ydk" / "retros" / f"{epic_id}.md").exists()
    assert [m.epic_id for m in find_epics_missing_retro(epic_repo, retros)] == [epic_id]
    answer = {"patterns": ["small PRs"], "templates": ["t"], "rules": ["r"], "summary": "went well"}
    assert _answer_requests(first.output, "retrospective", answer) == 1

    second = run()

    assert second.exit_code == 0, second.output
    text = (tmp_path / ".ydk" / "retros" / f"{epic_id}.md").read_text(encoding="utf-8")
    assert "small PRs" in text
    assert find_epics_missing_retro(epic_repo, retros) == []


@patch("ydk.cli.memory_cmd._get_extractor")
@patch("ydk.cli.memory_cmd._get_engine")
def test_memory_extract_two_phase_contradiction_handoff(
    mock_get_engine: MagicMock, mock_get_extractor: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ydk.core.contradiction_detector import ContradictionDetector
    from ydk.models.memory import ExtractedMemoryModel

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YDK_TEST_MISSING_KEY", raising=False)
    _write_subagent_config(tmp_path, "contradiction")
    engine = _mock_engine()

    def _find(content: str, concepts: list[str], detector: ContradictionDetector):
        detector.llm.judge_contradiction(content, "old fact")  # type: ignore[union-attr]
        return []

    engine.find_contradictions.side_effect = _find
    mock_get_engine.return_value = engine
    mock_get_extractor.return_value.extract_from_jsonl.return_value = [
        ExtractedMemoryModel(memory_type="decision", content="Use SQLite", concepts=["db"])
    ]
    jsonl_file = tmp_path / "session.jsonl"
    jsonl_file.write_text("{}\n")
    args = ["memory", "extract", "T-001", "--jsonl", str(jsonl_file)]

    first = runner.invoke(app, args)

    assert first.exit_code == 3, first.output
    engine.add_extraction.assert_not_called()
    assert _answer_requests(first.output, "contradiction", {"contradicts": True, "reason": "changed"}) == 1

    second = runner.invoke(app, args)

    assert second.exit_code == 0, second.output
    kwargs = engine.add_extraction.call_args.kwargs
    assert kwargs["concepts"] == ["db"]
    assert isinstance(kwargs["contradiction_detector"], ContradictionDetector)
    assert kwargs["contradictions"] == []

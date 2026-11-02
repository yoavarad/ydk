"""Checkpoint review-guide integration in TaskLifecycle.done / .checkpoint."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ydk.core.events import EventBus
from ydk.core.task_lifecycle import TaskLifecycle
from ydk.models.config import AIConfig, ProjectConfig, YdkConfig
from ydk.models.pm import TaskDetail
from ydk.models.verification import CheckResult, VerificationReport

DIFF = "--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1 @@\n-a\n+b\n"
PASS_REPORT = VerificationReport(
    timestamp="2025-01-01T00:00:00Z",
    checks=[CheckResult(name="tests", passed=True, output="ok", duration_seconds=1.0)],
    all_passed=True,
    total_duration_seconds=1.0,
)
PENDING_REPORT = VerificationReport(
    timestamp="2025-01-01T00:00:00Z",
    checks=[
        CheckResult(
            name="ai-code-review",
            passed=False,
            output="waiting",
            duration_seconds=0.0,
            detail={"status": "NEEDS_LLM", "request_paths": ["/r/a.json"], "no_cache": True},
        )
    ],
    all_passed=False,
    total_duration_seconds=1.0,
)


@pytest.fixture
def lc(tmp_path: Path) -> TaskLifecycle:
    repo = MagicMock()
    repo.get_task.return_value = TaskDetail(id="T-001", title="Test task", story_id="S-001", status="open")
    worktree = MagicMock()
    worktree.get_worktree_path.return_value = tmp_path
    verifier = MagicMock()
    verifier.discover_plugins.return_value = []
    verifier.filter_by_name.return_value = []
    verifier.run_all = AsyncMock(return_value=PASS_REPORT)
    (tmp_path / ".ydk").mkdir()
    return TaskLifecycle(repo=repo, events=EventBus(), worktree_mgr=worktree, verifier=verifier, project_root=tmp_path)


def _route(tmp_path: Path, provider: str) -> None:
    (tmp_path / ".ydk" / "config.yaml").write_text(
        f"project:\n  name: p\nai:\n  routes:\n    checkpoint: {provider}\n", encoding="utf-8"
    )


def test_checkpoint_none_when_no_diff(lc: TaskLifecycle) -> None:
    with patch("ydk.core.checkpoint.diff_against_base", return_value=""):
        assert lc.checkpoint("T-001") is None


def test_checkpoint_fallback_when_route_disabled(lc: TaskLifecycle) -> None:
    cfg = YdkConfig(project=ProjectConfig(name="p"), ai=AIConfig(routes={"checkpoint": "none"}))
    with patch("ydk.core.checkpoint.diff_against_base", return_value=DIFF):
        preview = lc.checkpoint("T-001", cfg)
    assert preview is not None
    assert preview.concerns[0].concern == "src"


def test_done_writes_checkpoint_proof_and_pr_body(lc: TaskLifecycle, tmp_path: Path) -> None:
    _route(tmp_path, "none")
    captured: dict[str, str] = {}

    def fake_create_pr(task_id: str, **kw: str) -> str:
        captured["body"] = kw["pr_body_override"]
        return "https://x/pr/1"

    with (
        patch("ydk.core.checkpoint.diff_against_base", return_value=DIFF),
        patch.object(lc, "_create_pr", side_effect=fake_create_pr),
    ):
        result = lc.done("T-001")

    assert result["passed"] is True
    assert (tmp_path / ".ydk" / "proofs" / "T-001" / "checkpoint.md").is_file()
    assert "## Review guide" in captured["body"]


def test_done_single_handoff_covers_plugins_and_checkpoint(lc: TaskLifecycle, tmp_path: Path) -> None:
    _route(tmp_path, "subagent")
    lc._verifier.run_all = AsyncMock(return_value=PENDING_REPORT)
    with patch("ydk.core.checkpoint.diff_against_base", return_value=DIFF):
        result = lc.done("T-001")
    assert result["passed"] is False
    assert result["needs_llm"][0] == "/r/a.json"
    assert len(result["needs_llm"]) == 2
    assert "checkpoint" in Path(result["needs_llm"][1]).read_text(encoding="utf-8")


def test_done_checkpoint_only_handoff_creates_no_pr(lc: TaskLifecycle, tmp_path: Path) -> None:
    _route(tmp_path, "subagent")
    with (
        patch("ydk.core.checkpoint.diff_against_base", return_value=DIFF),
        patch.object(lc, "_create_pr") as create_pr,
    ):
        result = lc.done("T-001")
    assert len(result["needs_llm"]) == 1
    create_pr.assert_not_called()


def test_done_removes_stale_checkpoint_file(lc: TaskLifecycle, tmp_path: Path) -> None:
    _route(tmp_path, "none")
    stale = tmp_path / ".ydk" / "proofs" / "T-001" / "checkpoint.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("old guide", encoding="utf-8")
    with (
        patch("ydk.core.checkpoint.diff_against_base", return_value=""),
        patch.object(lc, "_create_pr", return_value="https://x/pr/1"),
    ):
        lc.done("T-001")
    assert not stale.exists()

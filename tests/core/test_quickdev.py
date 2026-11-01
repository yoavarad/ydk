"""Tests for quick dev fast path."""

from __future__ import annotations

import json
import re
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from ydk.core.quickdev import QuickDevSetup, _generate_task_id, _slugify
from ydk.repositories.local.tasks import LocalTaskRepository

if TYPE_CHECKING:
    from pathlib import Path
from ydk.models.quickdev import QuickDevContext


def _init_main_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(
        [
            *["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"],
            *["commit", "-q", "--allow-empty", "-m", "init"],
        ],
        cwd=root,
        check=True,
    )


class TestGenerateTaskId:
    def test_produces_qd_prefix(self) -> None:
        tid = _generate_task_id("fix the bug")
        assert tid.startswith("QD-")

    def test_deterministic(self) -> None:
        a = _generate_task_id("same description")
        b = _generate_task_id("same description")
        assert a == b

    def test_different_for_different_input(self) -> None:
        a = _generate_task_id("fix A")
        b = _generate_task_id("fix B")
        assert a != b


class TestSlugify:
    def test_basic_slugify(self) -> None:
        assert _slugify("Hello World") == "hello-world"

    def test_special_chars(self) -> None:
        result = _slugify("fix: the bug!")
        assert result == "fix-the-bug"

    def test_max_length(self) -> None:
        result = _slugify("a" * 100, max_len=10)
        assert len(result) <= 10


class TestQuickDevSetup:
    def test_creates_task_file(self, tmp_path: Path) -> None:
        # Initialize a git repo so branch creation works
        _init_main_repo(tmp_path)

        setup = QuickDevSetup()
        result = setup.setup("add user avatar", tmp_path)

        assert isinstance(result, QuickDevContext)
        assert result.task_id.startswith("QD-")
        assert "add-user-avatar" in result.branch
        assert result.description == "add user avatar"

        # Task file should exist
        task_file = tmp_path / ".ydk" / "tasks" / f"{result.task_id}.md"
        assert task_file.exists()
        content = task_file.read_text()
        assert "add user avatar" in content
        assert "status: in-progress" in content

    def test_task_file_title_with_colon_is_valid_frontmatter(self, tmp_path: Path) -> None:
        _init_main_repo(tmp_path)

        result = QuickDevSetup().setup("fix(cli): support quick tasks", tmp_path)
        task = LocalTaskRepository(tmp_path / ".ydk").get_task(result.task_id)

        assert task.title == "fix(cli): support quick tasks"

    @pytest.mark.parametrize(
        "title",
        [
            "Fix: handle #123 case",
            "add thing # not a comment",
            "say \"hi\" and 'bye'",
            "- leading dash",
            "[leading bracket] item",
            "line one\nline two",
        ],
    )
    def test_task_file_title_round_trips_exactly(self, tmp_path: Path, title: str) -> None:
        _init_main_repo(tmp_path)
        result = QuickDevSetup().setup(title, tmp_path)
        task = LocalTaskRepository(tmp_path / ".ydk").get_task(result.task_id)

        assert task.title == title

    def test_finds_relevant_components(self, tmp_path: Path) -> None:
        _init_main_repo(tmp_path)
        # Create components
        components = tmp_path / ".ydk" / "components"
        components.mkdir(parents=True)
        (components / "avatar.yaml").write_text("id: avatar")
        (components / "order.yaml").write_text("id: order")

        setup = QuickDevSetup()
        result = setup.setup("fix avatar upload", tmp_path)
        assert "avatar" in result.components

    def test_context_output(self, tmp_path: Path) -> None:
        _init_main_repo(tmp_path)

        setup = QuickDevSetup()
        result = setup.setup("update readme", tmp_path)
        assert result.testing_guidance != ""
        assert result.branch.startswith("chore/")


class TestBranchNaming:
    """Branch names must satisfy the CI branch-name gate (.github/workflows/ci.yml)."""

    CI_BRANCH_RE = re.compile(r"^(feat|fix|docs|chore|refactor|test|ci|perf|release|task)/[a-z0-9-]+$")

    def _init_repo(self, tmp_path: Path) -> None:
        _init_main_repo(tmp_path)

    def test_conventional_prefix_is_used_as_branch_type(self, tmp_path: Path) -> None:
        self._init_repo(tmp_path)
        result = QuickDevSetup().setup("docs: update the readme", tmp_path)
        assert result.branch.startswith("docs/")
        assert self.CI_BRANCH_RE.match(result.branch)

    def test_no_conventional_prefix_defaults_to_chore(self, tmp_path: Path) -> None:
        self._init_repo(tmp_path)
        result = QuickDevSetup().setup("make it faster", tmp_path)
        assert result.branch.startswith("chore/")
        assert self.CI_BRANCH_RE.match(result.branch)

    def test_non_ascii_description_yields_ascii_only_branch(self, tmp_path: Path) -> None:
        self._init_repo(tmp_path)
        result = QuickDevSetup().setup("fix café — açcént bug", tmp_path)
        assert self.CI_BRANCH_RE.match(result.branch)

    def test_task_id_is_lowercased_in_branch_but_not_in_task_file(self, tmp_path: Path) -> None:
        self._init_repo(tmp_path)
        result = QuickDevSetup().setup("fix the bug", tmp_path)

        assert "QD-" in result.task_id
        assert "QD-" not in result.branch
        assert result.task_id.lower() in result.branch
        assert self.CI_BRANCH_RE.match(result.branch)

        task_file = tmp_path / ".ydk" / "tasks" / f"{result.task_id}.md"
        content = task_file.read_text()
        assert f"id: {result.task_id}" in content


class TestQuickDevGithubRemote:
    """remote=github: quick creates a github issue via the task repository."""

    def _init_repo(self, tmp_path: Path) -> None:
        _init_main_repo(tmp_path)

    def test_creates_issue_no_qd_file_and_active_task(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._init_repo(tmp_path)
        (tmp_path / ".ydk").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".ydk" / "config.yaml").write_text("project:\n  name: test\n  remote: github\n")
        monkeypatch.chdir(tmp_path)

        fake_result = MagicMock(returncode=0, stdout="https://github.com/org/repo/issues/42\n", stderr="")
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake_result) as mock_run:
            result = QuickDevSetup().setup("fix avatar upload", tmp_path)

        mock_run.assert_called_once()
        assert result.task_id == "42"
        assert "42" in result.branch
        assert not result.task_id.startswith("QD-")

        tasks_dir = tmp_path / ".ydk" / "tasks"
        assert not tasks_dir.exists() or list(tasks_dir.glob("QD-*.md")) == []

        active = json.loads((tmp_path / ".ydk" / "active-task.json").read_text())
        assert active["tasks"]["42"]["base_branch"] == "main"

    def test_branch_type_and_slug_preserved(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._init_repo(tmp_path)
        (tmp_path / ".ydk").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".ydk" / "config.yaml").write_text("project:\n  name: test\n  remote: github\n")
        monkeypatch.chdir(tmp_path)

        fake_result = MagicMock(returncode=0, stdout="https://github.com/org/repo/issues/7\n", stderr="")
        with patch("ydk.repositories.github.tasks.run_gh", return_value=fake_result):
            result = QuickDevSetup().setup("docs: update the readme", tmp_path)

        assert result.branch.startswith("docs/")
        assert result.branch == "docs/7-docs-update-the-readme"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_repo_with_origin_head(root: Path, branch: str) -> None:
    _git(root, "init", "-q", "-b", branch)
    _git(root, "commit", "-q", "--allow-empty", "-m", "init")
    _git(root, "branch", "-q", "develop")
    subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{branch}"],
        cwd=root,
        check=True,
    )


class TestQuickDevBase:
    def test_explicit_base_recorded(self, tmp_path: Path) -> None:
        _git_repo_with_origin_head(tmp_path, "trunk")
        ctx = QuickDevSetup().setup("fix: thing", tmp_path, base_branch="develop")
        data = json.loads((tmp_path / ".ydk" / "active-task.json").read_text(encoding="utf-8"))
        assert data["tasks"][ctx.task_id]["base_branch"] == "develop"

    def test_default_base_is_repo_default_branch(self, tmp_path: Path) -> None:
        _git_repo_with_origin_head(tmp_path, "trunk")
        ctx = QuickDevSetup().setup("fix: thing", tmp_path)
        data = json.loads((tmp_path / ".ydk" / "active-task.json").read_text(encoding="utf-8"))
        assert data["tasks"][ctx.task_id]["base_branch"] == "trunk"


class TestQuickDevWorktree:
    """quick never touches the main checkout; it forks an isolated worktree from the base."""

    def test_main_checkout_unchanged_and_worktree_created(self, tmp_path: Path) -> None:
        _git_repo_with_origin_head(tmp_path, "trunk")
        head_before = _git(tmp_path, "rev-parse", "HEAD")
        ctx = QuickDevSetup().setup("fix: thing", tmp_path, base_branch="develop")

        assert _git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD") == "trunk"
        assert _git(tmp_path, "rev-parse", "HEAD") == head_before
        wt = tmp_path / ".ydk" / "worktrees" / ctx.task_id
        assert wt.is_dir()
        assert ctx.worktree == str(wt)
        assert _git(wt, "rev-parse", "--abbrev-ref", "HEAD") == ctx.branch

    def test_branch_forks_from_base_not_current_head(self, tmp_path: Path) -> None:
        _git_repo_with_origin_head(tmp_path, "trunk")
        (tmp_path / "unrelated.txt").write_text("x\n")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "unrelated on trunk")
        ctx = QuickDevSetup().setup("fix: thing", tmp_path, base_branch="develop")

        wt = tmp_path / ".ydk" / "worktrees" / ctx.task_id
        assert _git(wt, "rev-parse", "HEAD") == _git(tmp_path, "rev-parse", "develop")
        assert not (wt / "unrelated.txt").exists()

    def test_without_base_forks_from_default_branch(self, tmp_path: Path) -> None:
        _git_repo_with_origin_head(tmp_path, "trunk")
        _git(tmp_path, "checkout", "-q", "develop")
        (tmp_path / "dev.txt").write_text("d\n")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "develop only")
        _git(tmp_path, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        ctx = QuickDevSetup().setup("fix: thing", tmp_path)

        wt = tmp_path / ".ydk" / "worktrees" / ctx.task_id
        assert _git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD") == "develop"
        assert _git(wt, "rev-parse", "HEAD") == _git(tmp_path, "rev-parse", "trunk")

    def test_missing_base_raises(self, tmp_path: Path) -> None:
        _git_repo_with_origin_head(tmp_path, "trunk")
        with pytest.raises(ValueError, match="nope"):
            QuickDevSetup().setup("fix: thing", tmp_path, base_branch="nope")
        assert not (tmp_path / ".ydk" / "worktrees").exists()

    def test_git_failure_raises_runtime_error(self, tmp_path: Path) -> None:
        _git_repo_with_origin_head(tmp_path, "trunk")
        QuickDevSetup().setup("fix: thing", tmp_path)
        with pytest.raises(RuntimeError, match="worktree"):
            QuickDevSetup().setup("fix: thing", tmp_path)

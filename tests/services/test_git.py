"""Tests for LocalGitService — unit tests (mocked subprocess) and integration tests (real git repo)."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ydk.services.git import LocalGitService

# ---------------------------------------------------------------------------
# Unit tests — mocked subprocess
# ---------------------------------------------------------------------------


class TestChangedFilesUnit:
    """changed_files with mocked subprocess."""

    def test_returns_filtered_md_files(self) -> None:
        svc = LocalGitService()
        fake_result = MagicMock(returncode=0, stdout="docs/a.md\ndocs/b.md\nsrc/c.py\n")
        with patch("subprocess.run", return_value=fake_result) as mock_run:
            result = svc.changed_files("docs", base_ref="main", extension=".md")
        assert result == ["docs/a.md", "docs/b.md"]
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs.get("encoding") == "utf-8"

    def test_falls_back_to_ls_files_on_diff_failure(self) -> None:
        svc = LocalGitService()
        fail_result = MagicMock(returncode=128, stdout="", stderr="fatal: bad ref")
        ok_result = MagicMock(returncode=0, stdout="docs/a.md\ndocs/b.txt\n")
        with patch("subprocess.run", side_effect=[fail_result, ok_result]) as mock_run:
            result = svc.changed_files("docs", base_ref="nonexistent", extension=".md")
        assert result == ["docs/a.md"]
        assert all(call.kwargs.get("encoding") == "utf-8" for call in mock_run.call_args_list)

    def test_returns_empty_on_no_output(self) -> None:
        svc = LocalGitService()
        fake_result = MagicMock(returncode=0, stdout="")
        with patch("subprocess.run", return_value=fake_result):
            result = svc.changed_files("docs")
        assert result == []


class TestCurrentBranchUnit:
    """current_branch with mocked subprocess."""

    def test_returns_branch_name(self) -> None:
        svc = LocalGitService()
        fake_result = MagicMock(returncode=0, stdout="feature/cool\n")
        with patch("subprocess.run", return_value=fake_result) as mock_run:
            assert svc.current_branch() == "feature/cool"
        assert mock_run.call_args.kwargs.get("encoding") == "utf-8"

    def test_raises_on_failure(self) -> None:
        svc = LocalGitService()
        fake_result = MagicMock(returncode=128, stdout="", stderr="not a git repo")
        with patch("subprocess.run", return_value=fake_result), pytest.raises(RuntimeError):
            svc.current_branch()


# ---------------------------------------------------------------------------
# Integration tests — real git repo in tmp_path
# ---------------------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with some .md files."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)

    # Create files and initial commit on main
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "one.md").write_text("# One")
    (docs / "two.md").write_text("# Two")
    (docs / "skip.txt").write_text("not markdown")
    (tmp_path / "root.py").write_text("x = 1")

    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=tmp_path, capture_output=True, check=True)

    # Create a feature branch and add a new file
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=tmp_path, capture_output=True, check=True)
    (docs / "three.md").write_text("# Three")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "add three"], cwd=tmp_path, capture_output=True, check=True)

    return tmp_path


class TestAllFilesIntegration:
    def test_finds_md_files(self, git_repo: Path) -> None:
        svc = LocalGitService()
        docs_dir = str(git_repo / "docs")
        result = svc.all_files(docs_dir, extension=".md")
        basenames = sorted(Path(f).name for f in result)
        assert basenames == ["one.md", "three.md", "two.md"]

    def test_finds_txt_files(self, git_repo: Path) -> None:
        svc = LocalGitService()
        docs_dir = str(git_repo / "docs")
        result = svc.all_files(docs_dir, extension=".txt")
        assert len(result) == 1
        assert Path(result[0]).name == "skip.txt"

    def test_empty_for_missing_dir(self, tmp_path: Path) -> None:
        svc = LocalGitService()
        result = svc.all_files(str(tmp_path / "nonexistent"), extension=".md")
        assert result == []


class TestReadContentIntegration:
    def test_concatenates_with_headers(self, git_repo: Path) -> None:
        svc = LocalGitService()
        files = [str(git_repo / "docs" / "one.md"), str(git_repo / "docs" / "two.md")]
        content = svc.read_content(files)
        assert "# File: " in content
        assert "one.md" in content
        assert "# One" in content
        assert "# Two" in content
        assert "---" in content

    def test_skips_missing_files(self, git_repo: Path) -> None:
        svc = LocalGitService()
        files = [str(git_repo / "docs" / "one.md"), str(git_repo / "docs" / "nope.md")]
        content = svc.read_content(files)
        assert "# One" in content
        # Should not crash

    def test_empty_list(self) -> None:
        svc = LocalGitService()
        assert svc.read_content([]) == ""

    def test_reads_text_as_utf8(self, git_repo: Path) -> None:
        svc = LocalGitService()
        target = git_repo / "docs" / "one.md"
        with patch.object(Path, "read_text", return_value="# One", autospec=True) as mock_read_text:
            svc.read_content([str(target)])
        assert mock_read_text.call_args.kwargs.get("encoding") == "utf-8"


class TestChangedFilesIntegration:
    def test_detects_changed_md_on_branch(self, git_repo: Path) -> None:
        svc = LocalGitService(cwd=str(git_repo))
        changed = svc.changed_files("docs", base_ref="main", extension=".md")
        assert any("three.md" in f for f in changed)


class TestCurrentBranchIntegration:
    def test_returns_current_branch(self, git_repo: Path) -> None:
        svc = LocalGitService(cwd=str(git_repo))
        assert svc.current_branch() == "feature"


# ---------------------------------------------------------------------------
# default_branch resolver
# ---------------------------------------------------------------------------


class TestDefaultBranch:
    """default_branch: origin/HEAD, then gh, then 'main'."""

    def test_returns_origin_head_branch(self) -> None:
        from ydk.services.git import default_branch

        ok = MagicMock(returncode=0, stdout="origin/develop\n")
        with patch("subprocess.run", return_value=ok) as mock_run:
            assert default_branch(".") == "develop"
        assert mock_run.call_count == 1

    def test_slash_named_branch_keeps_path(self) -> None:
        from ydk.services.git import default_branch

        ok = MagicMock(returncode=0, stdout="origin/release/1.x\n")
        with patch("subprocess.run", return_value=ok):
            assert default_branch(".") == "release/1.x"

    def test_falls_back_to_gh(self) -> None:
        from ydk.services.git import default_branch

        fail = MagicMock(returncode=128, stdout="")
        gh = MagicMock(returncode=0, stdout="trunk\n")
        with patch("subprocess.run", side_effect=[fail, gh]) as mock_run:
            assert default_branch(".") == "trunk"
        assert mock_run.call_args_list[1].args[0][0] == "gh"

    def test_falls_back_to_main_when_both_fail(self) -> None:
        from ydk.services.git import default_branch

        fail = MagicMock(returncode=1, stdout="")
        with patch("subprocess.run", return_value=fail):
            assert default_branch(".") == "main"

    def test_falls_back_to_main_when_gh_missing(self) -> None:
        from ydk.services.git import default_branch

        fail = MagicMock(returncode=128, stdout="")
        with patch("subprocess.run", side_effect=[fail, FileNotFoundError()]):
            assert default_branch(".") == "main"


@pytest.fixture(autouse=True)
def _hermetic_default_branch() -> None:
    """Override the conftest stub: these tests mock subprocess.run themselves."""
    from ydk.services import git as git_service

    git_service._default_branch_cached.cache_clear()
    yield
    git_service._default_branch_cached.cache_clear()


class TestDefaultBranchEdges:
    def test_blank_origin_head_output_falls_through_to_gh(self) -> None:
        from ydk.services.git import default_branch

        blank = MagicMock(returncode=0, stdout="  \n")
        gh = MagicMock(returncode=0, stdout="trunk\n")
        with patch("subprocess.run", side_effect=[blank, gh]):
            assert default_branch(".") == "trunk"

    def test_timeout_falls_back_to_main(self) -> None:
        from ydk.services.git import default_branch

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=1)):
            assert default_branch(".") == "main"

    def test_result_cached_per_repo_root(self, tmp_path: Path) -> None:
        from ydk.services.git import default_branch

        ok = MagicMock(returncode=0, stdout="origin/develop\n")
        with patch("subprocess.run", return_value=ok) as mock_run:
            assert default_branch(tmp_path) == "develop"
            assert default_branch(tmp_path) == "develop"
        assert mock_run.call_count == 1


class TestMergeBase:
    """merge_base: origin/<base> merge-base first, local <base> second, else None."""

    @staticmethod
    def _git(repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _commit(self, repo: Path, name: str) -> str:
        (repo / name).write_text(name)
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "-m", name)
        return self._git(repo, "rev-parse", "HEAD")

    def test_local_base_when_no_remote(self, tmp_path: Path) -> None:
        from ydk.services.git import merge_base

        self._git(tmp_path, "init", "-q", "-b", "develop")
        base = self._commit(tmp_path, "a")
        self._git(tmp_path, "checkout", "-q", "-b", "feature")
        self._commit(tmp_path, "b")
        assert merge_base("develop", tmp_path) == base

    def test_prefers_origin_ref_when_ahead_of_local(self, tmp_path: Path) -> None:
        from ydk.services.git import merge_base

        self._git(tmp_path, "init", "-q", "-b", "develop")
        self._commit(tmp_path, "a")
        self._git(tmp_path, "checkout", "-q", "-b", "feature")
        ahead = self._commit(tmp_path, "b")
        # origin/develop sits at the feature commit; local develop stays behind
        self._git(tmp_path, "update-ref", "refs/remotes/origin/develop", ahead)
        self._commit(tmp_path, "c")
        assert merge_base("develop", tmp_path) == ahead

    def test_strips_origin_prefix(self, tmp_path: Path) -> None:
        from ydk.services.git import merge_base

        self._git(tmp_path, "init", "-q", "-b", "develop")
        base = self._commit(tmp_path, "a")
        self._git(tmp_path, "update-ref", "refs/remotes/origin/develop", base)
        self._git(tmp_path, "checkout", "-q", "-b", "feature")
        self._commit(tmp_path, "b")
        assert merge_base("origin/develop", tmp_path) == base

    def test_none_when_no_ref_resolves(self, tmp_path: Path) -> None:
        from ydk.services.git import merge_base

        self._git(tmp_path, "init", "-q", "-b", "develop")
        self._commit(tmp_path, "a")
        assert merge_base("nope", tmp_path) is None

"""Tests for LocalGitService — unit tests (mocked subprocess) and integration tests (real git repo)."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from odk.services.git import LocalGitService

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

    def test_falls_back_to_ls_files_on_diff_failure(self) -> None:
        svc = LocalGitService()
        fail_result = MagicMock(returncode=128, stdout="", stderr="fatal: bad ref")
        ok_result = MagicMock(returncode=0, stdout="docs/a.md\ndocs/b.txt\n")
        with patch("subprocess.run", side_effect=[fail_result, ok_result]):
            result = svc.changed_files("docs", base_ref="nonexistent", extension=".md")
        assert result == ["docs/a.md"]

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
        with patch("subprocess.run", return_value=fake_result):
            assert svc.current_branch() == "feature/cool"

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


class TestChangedFilesIntegration:
    def test_detects_changed_md_on_branch(self, git_repo: Path) -> None:
        svc = LocalGitService(cwd=str(git_repo))
        changed = svc.changed_files("docs", base_ref="main", extension=".md")
        assert any("three.md" in f for f in changed)


class TestCurrentBranchIntegration:
    def test_returns_current_branch(self, git_repo: Path) -> None:
        svc = LocalGitService(cwd=str(git_repo))
        assert svc.current_branch() == "feature"

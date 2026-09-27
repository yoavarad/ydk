"""Tests for `ydk task merge-driver` and `ydk task install-merge-driver`."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from ydk.cli.task_cmd import task_app

runner = CliRunner()


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)


def _manifest(tasks: dict) -> str:
    return yaml.dump(
        {
            "last_task_id": 0,
            "last_story_id": 0,
            "last_epic_id": 0,
            "epics": {},
            "stories": {},
            "tasks": tasks,
        },
        sort_keys=False,
    )


class TestMergeDriverCommand:
    def test_writes_merged_result_into_ours(self, tmp_path: Path) -> None:
        base = tmp_path / "base"
        ours = tmp_path / "ours"
        theirs = tmp_path / "theirs"
        base.write_text(_manifest({}), encoding="utf-8")
        ours.write_text(_manifest({"T-1": {"status": "open"}}), encoding="utf-8")
        theirs.write_text(_manifest({"T-2": {"status": "done"}}), encoding="utf-8")

        result = runner.invoke(
            task_app,
            ["merge-driver", str(base), str(ours), str(theirs), ".ydk/manifest.yaml"],
        )

        assert result.exit_code == 0, result.output
        merged = yaml.safe_load(ours.read_text(encoding="utf-8"))
        assert merged["tasks"] == {"T-1": {"status": "open"}, "T-2": {"status": "done"}}

    def test_writes_lf_line_endings(self, tmp_path: Path) -> None:
        base = tmp_path / "base"
        ours = tmp_path / "ours"
        theirs = tmp_path / "theirs"
        base.write_bytes(_manifest({}).encode())
        ours.write_bytes(_manifest({"T-1": {"status": "open"}}).encode())
        theirs.write_bytes(_manifest({"T-2": {"status": "done"}}).encode())

        result = runner.invoke(
            task_app,
            ["merge-driver", str(base), str(ours), str(theirs), ".ydk/manifest.yaml"],
        )

        assert result.exit_code == 0, result.output
        assert b"\r\n" not in ours.read_bytes()

    def test_invalid_yaml_exits_nonzero_and_leaves_ours(self, tmp_path: Path) -> None:
        base = tmp_path / "base"
        ours = tmp_path / "ours"
        theirs = tmp_path / "theirs"
        base.write_text(_manifest({}), encoding="utf-8")
        ours.write_text("tasks: [unclosed", encoding="utf-8")
        theirs.write_text(_manifest({}), encoding="utf-8")

        result = runner.invoke(
            task_app,
            ["merge-driver", str(base), str(ours), str(theirs), ".ydk/manifest.yaml"],
        )

        assert result.exit_code != 0
        assert ours.read_text(encoding="utf-8") == "tasks: [unclosed"


@pytest.fixture
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@test.com")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "core.autocrlf", "false")
    (tmp_path / ".ydk" / "tasks").mkdir(parents=True)
    (tmp_path / ".ydk" / "manifest.yaml").write_text(_manifest({}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestInstallMergeDriver:
    def test_configures_git_and_gitattributes(self, git_repo: Path) -> None:
        result = runner.invoke(task_app, ["install-merge-driver"])

        assert result.exit_code == 0, result.output
        driver = _git(git_repo, "config", "--get", "merge.ydk-bookkeeping.driver")
        assert driver.stdout.strip() == "ydk task merge-driver %O %A %B %P"
        attrs = (git_repo / ".gitattributes").read_text(encoding="utf-8")
        assert ".ydk/manifest.yaml merge=ydk-bookkeeping" in attrs
        assert ".ydk/tasks/*.md merge=ydk-bookkeeping" in attrs

    def test_is_idempotent(self, git_repo: Path) -> None:
        runner.invoke(task_app, ["install-merge-driver"])
        runner.invoke(task_app, ["install-merge-driver"])

        attrs = (git_repo / ".gitattributes").read_text(encoding="utf-8")
        assert attrs.count(".ydk/manifest.yaml merge=ydk-bookkeeping") == 1
        assert b"\r\n" not in (git_repo / ".gitattributes").read_bytes()

    def test_two_branches_adding_different_tasks_merge_cleanly(self, git_repo: Path) -> None:
        python = Path(sys.executable).as_posix()
        result = runner.invoke(
            task_app,
            ["install-merge-driver", "--command", f'"{python}" -m ydk'],
        )
        assert result.exit_code == 0, result.output
        _git(git_repo, "add", ".")
        _git(git_repo, "commit", "-m", "init")

        manifest = git_repo / ".ydk" / "manifest.yaml"
        _git(git_repo, "checkout", "-b", "a")
        manifest.write_text(_manifest({"T-1": {"status": "open"}}), encoding="utf-8")
        _git(git_repo, "commit", "-am", "add T-1")

        _git(git_repo, "checkout", "main")
        _git(git_repo, "checkout", "-b", "b")
        manifest.write_text(_manifest({"T-2": {"status": "done"}}), encoding="utf-8")
        _git(git_repo, "commit", "-am", "add T-2")

        merge = _git(git_repo, "merge", "--no-edit", "a")

        assert merge.returncode == 0, merge.stdout + merge.stderr
        merged = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        assert set(merged["tasks"]) == {"T-1", "T-2"}

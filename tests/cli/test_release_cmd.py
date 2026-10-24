"""Tests for `ydk release` — git/gh/cz are faked at the subprocess boundary."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from ydk.cli import app, release_cmd
from ydk.core.pr_body_check import run_pr_body_validation

if TYPE_CHECKING:
    import pytest

runner = CliRunner()

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CHANGELOG = """## v1.7.0 (2026-10-24)

### Feat

- **release**: add ydk release command

### Fix

- **task**: fix a thing

## v1.6.0 (2026-10-16)

### Feat

- older entry
"""

PR_URL = "https://github.com/yoavarad/ydk/pull/999"


class FakeProcs:
    """Answers git/gh/cz commands by argv prefix and records every call."""

    def __init__(self, **overrides: tuple[int, str]) -> None:
        self.calls: list[list[str]] = []
        self.inputs: dict[str, str | None] = {}
        self.answers: dict[str, tuple[int, str]] = {
            "git rev-parse --abbrev-ref HEAD": (0, "main\n"),
            "git status --porcelain --untracked-files=no": (0, ""),
            "git fetch origin main": (0, ""),
            "git rev-parse HEAD": (0, "abc123\n"),
            "git rev-parse origin/main": (0, "abc123\n"),
            "cz bump --get-next": (0, "1.7.0\n"),
            "cz changelog --dry-run": (0, CHANGELOG),
            "git checkout -b": (0, ""),
            "cz bump --yes": (0, "bump: version 1.6.0 → 1.7.0\n"),
            "git rev-list --count origin/main..HEAD": (0, "1\n"),
            "git show --name-only --format= HEAD": (0, "CHANGELOG.md\npyproject.toml\nuv.lock\n"),
            "git push": (0, ""),
            "gh pr create": (0, PR_URL + "\n"),
        }
        self.answers.update(overrides)

    def __call__(self, cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        joined = " ".join(cmd)
        stdin = kwargs.get("input")
        self.inputs[joined] = stdin if isinstance(stdin, str) else None
        for prefix in sorted(self.answers, key=len, reverse=True):
            if joined.startswith(prefix):
                rc, out = self.answers[prefix]
                return subprocess.CompletedProcess(cmd, rc, out, "boom" if rc else "")
        raise AssertionError(f"unexpected command: {joined}")

    def ran(self, prefix: str) -> bool:
        return any(" ".join(c).startswith(prefix) for c in self.calls)


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeProcs) -> FakeProcs:
    monkeypatch.setattr(release_cmd.subprocess, "run", fake)
    return fake


def test_dry_run_prints_version_branch_and_body_without_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs())
    result = runner.invoke(app, ["release", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "1.7.0" in result.output
    assert "release/v1.7.0" in result.output
    assert "## Summary" in result.output
    assert "add ydk release command" in result.output
    for mutating in ("git checkout", "cz bump --yes", "git push", "gh pr create"):
        assert not fake.ran(mutating), mutating


def test_dry_run_passes_increment_to_cz(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs())
    result = runner.invoke(app, ["release", "--dry-run", "--increment", "MAJOR"])
    assert result.exit_code == 0, result.output
    assert ["cz", "bump", "--get-next", "--increment", "MAJOR"] in fake.calls


def test_refuses_on_non_main_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs(**{"git rev-parse --abbrev-ref HEAD": (0, "feat/x\n")}))
    result = runner.invoke(app, ["release", "--dry-run"])
    assert result.exit_code == 1
    assert "main" in result.output
    assert not fake.ran("cz")


def test_refuses_on_dirty_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs(**{"git status --porcelain --untracked-files=no": (0, " M foo.py\n")}))
    result = runner.invoke(app, ["release"])
    assert result.exit_code == 1
    assert "clean" in result.output
    assert not fake.ran("cz")


def test_refuses_when_main_behind_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs(**{"git rev-parse origin/main": (0, "def456\n")}))
    result = runner.invoke(app, ["release"])
    assert result.exit_code == 1
    assert "origin/main" in result.output
    assert not fake.ran("cz")


def test_full_release_runs_steps_in_order_and_prints_url(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs())
    result = runner.invoke(app, ["release", "--increment", "PATCH"])
    assert result.exit_code == 0, result.output
    assert PR_URL in result.output
    joined = [" ".join(c) for c in fake.calls]
    order = [
        "git checkout -b release/v1.7.0",
        "cz bump --yes --increment PATCH",
        "git push -u origin release/v1.7.0",
        "gh pr create",
    ]
    idx = [next(i for i, c in enumerate(joined) if c.startswith(o)) for o in order]
    assert idx == sorted(idx)
    pr_cmd = next(c for c in fake.calls if c[:3] == ["gh", "pr", "create"])
    assert pr_cmd[pr_cmd.index("--title") + 1] == "release: v1.7.0"
    assert pr_cmd[pr_cmd.index("--base") + 1] == "main"
    body = fake.inputs[" ".join(pr_cmd)]
    assert body is not None
    assert "## Summary" in body


def test_aborts_before_push_when_bump_commit_has_wrong_files(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(
        monkeypatch, FakeProcs(**{"git show --name-only --format= HEAD": (0, "pyproject.toml\nCHANGELOG.md\n")})
    )
    result = runner.invoke(app, ["release"])
    assert result.exit_code == 1
    assert "got 1 commit(s) touching CHANGELOG.md, pyproject.toml" in result.output
    assert "git branch -D release/v1.7.0" in result.output
    assert not fake.ran("git push")


def test_aborts_before_push_when_more_than_one_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs(**{"git rev-list --count origin/main..HEAD": (0, "2\n")}))
    result = runner.invoke(app, ["release"])
    assert result.exit_code == 1
    assert not fake.ran("git push")


def test_failed_cz_bump_stops_release(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs(**{"cz bump --yes": (1, "")}))
    result = runner.invoke(app, ["release"])
    assert result.exit_code == 1
    assert not fake.ran("git push")


def test_changelog_section_keeps_only_newest_release() -> None:
    section = release_cmd.changelog_section(CHANGELOG)
    assert "add ydk release command" in section
    assert "fix a thing" in section
    assert "older entry" not in section
    assert "## v1.7.0" not in section


def test_pr_body_passes_pr_body_validation() -> None:
    body = release_cmd.render_pr_body("1.7.0", release_cmd.changelog_section(CHANGELOG))
    result = run_pr_body_validation(body, ["pyproject.toml", "uv.lock", "CHANGELOG.md"], PROJECT_ROOT)
    assert result is not None
    assert result.passed, result.output


def test_pr_body_console_block_reflects_increment(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, FakeProcs())
    result = runner.invoke(app, ["release", "--dry-run", "--increment", "MINOR"])
    assert result.exit_code == 0, result.output
    assert "$ cz bump --get-next --increment MINOR" in result.output


def test_prints_last_line_of_gh_output_as_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, FakeProcs(**{"gh pr create": (0, f"Creating pull request...\n{PR_URL}\n")}))
    result = runner.invoke(app, ["release"])
    assert result.exit_code == 0, result.output
    assert result.output.strip().splitlines()[-1] == PR_URL

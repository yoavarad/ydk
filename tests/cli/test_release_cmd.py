"""Tests for `ydk release` — git/gh/cz are faked at the subprocess boundary."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ydk.cli import app, release_cmd
from ydk.core.pr_body_check import run_pr_body_validation

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
        self.envs: dict[str, object] = {}
        self.bump_creates_tag = False
        self.raises: dict[str, BaseException] = {}
        self.answers: dict[str, tuple[int, str]] = {
            "git rev-parse --verify --quiet refs/heads/": (1, ""),
            "git rev-parse --verify --quiet refs/tags/": (1, ""),
            "git ls-remote --exit-code --heads origin": (2, ""),
            "git checkout": (0, ""),
            "git reset --hard": (0, ""),
            "git branch -D": (0, ""),
            "git tag -d": (0, ""),
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
        self.envs[joined] = kwargs.get("env")
        if self.bump_creates_tag and joined.startswith("cz bump --yes"):
            self.answers["git rev-parse --verify --quiet refs/tags/"] = (0, "deadbeef\n")
        for prefix, exc in self.raises.items():
            if joined.startswith(prefix):
                raise exc
        for prefix in sorted(self.answers, key=len, reverse=True):
            if joined.startswith(prefix):
                rc, out = self.answers[prefix]
                if rc == 0 and joined.startswith("git push -u"):
                    self.answers["git ls-remote --exit-code --heads origin"] = (0, "")
                return subprocess.CompletedProcess(cmd, rc, out, "boom" if rc else "")
        raise AssertionError(f"unexpected command: {joined}")

    def ran(self, prefix: str) -> bool:
        return any(" ".join(c).startswith(prefix) for c in self.calls)


@pytest.fixture(autouse=True)
def _tools_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release_cmd.shutil, "which", lambda name: f"/usr/bin/{name}")


def _hide(monkeypatch: pytest.MonkeyPatch, *missing: str) -> None:
    monkeypatch.setattr(release_cmd.shutil, "which", lambda name: None if name in missing else f"/usr/bin/{name}")


@pytest.mark.parametrize("tool", ["git", "cz", "gh"])
def test_preflight_refuses_when_tool_missing(monkeypatch: pytest.MonkeyPatch, tool: str) -> None:
    fake = _install(monkeypatch, FakeProcs())
    _hide(monkeypatch, tool)
    result = runner.invoke(app, ["release"])
    assert result.exit_code == 1
    assert not isinstance(result.exception, FileNotFoundError)
    assert f"required tool '{tool}' not found on PATH" in result.output
    assert fake.calls == []


def test_preflight_dry_run_does_not_need_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, FakeProcs())
    _hide(monkeypatch, "gh")
    result = runner.invoke(app, ["release", "--dry-run"])
    assert result.exit_code == 0, result.output


def test_preflight_dry_run_still_needs_cz(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs())
    _hide(monkeypatch, "cz")
    result = runner.invoke(app, ["release", "--dry-run"])
    assert result.exit_code == 1
    assert "'cz' not found" in result.output
    assert fake.calls == []


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


def test_dry_run_works_from_feature_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs(**{"git rev-parse --abbrev-ref HEAD": (0, "feat/x\n")}))
    result = runner.invoke(app, ["release", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "release/v1.7.0" in result.output
    assert not fake.ran("git checkout")


def test_dry_run_works_from_detached_head(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs(**{"git rev-parse --abbrev-ref HEAD": (0, "HEAD\n")}))
    result = runner.invoke(app, ["release", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert ["git", "rev-parse", "HEAD"] in fake.calls
    assert not fake.ran("git checkout")


def test_dry_run_notes_when_head_differs_from_origin_main(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs(**{"git rev-parse origin/main": (0, "def456\n")}))
    result = runner.invoke(app, ["release", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Note: previewing from main, not origin/main" in result.output
    assert not fake.ran("git checkout")


def test_refuses_on_dirty_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs(**{"git status --porcelain --untracked-files=no": (0, " M foo.py\n")}))
    result = runner.invoke(app, ["release"])
    assert result.exit_code == 1
    assert "clean" in result.output
    assert not fake.ran("cz")


def test_stale_main_is_rebased_onto_origin_main_before_branching(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs(**{"git rev-parse origin/main": (0, "def456\n")}))
    result = runner.invoke(app, ["release"])
    assert result.exit_code == 0, result.output
    joined = [" ".join(c) for c in fake.calls]
    assert joined.index("git checkout --detach origin/main") < joined.index("git checkout -b release/v1.7.0")


def test_subprocesses_run_with_uv_no_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs())
    result = runner.invoke(app, ["release"])
    assert result.exit_code == 0, result.output
    for cmd in ("cz bump --yes", "git push -u origin release/v1.7.0"):
        env = fake.envs[cmd]
        assert isinstance(env, dict)
        assert env["UV_NO_SYNC"] == "1"


def test_precheck_refuses_when_local_branch_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs(**{"git rev-parse --verify --quiet refs/heads/": (0, "abc\n")}))
    result = runner.invoke(app, ["release"])
    assert result.exit_code == 1
    assert "git branch -D release/v1.7.0" in result.output
    assert not fake.ran("cz bump --yes")
    assert not fake.ran("git checkout -b")


_FAILURES = {
    "bump": ({"cz bump --yes": (1, "")}, False),
    "wrong-files": ({"git show --name-only --format= HEAD": (0, "pyproject.toml\n")}, False),
    "push": ({"git push -u": (1, "")}, False),
    "gh": ({"gh pr create": (1, "")}, True),
}


@pytest.mark.parametrize("name", list(_FAILURES))
def test_failure_rolls_back_and_retry_succeeds(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    overrides, pushed = _FAILURES[name]
    fake = _install(monkeypatch, FakeProcs(**overrides))
    result = runner.invoke(app, ["release"])
    assert result.exit_code == 1
    assert "Release aborted; rolled back to main." in result.output
    assert fake.ran("git checkout main")
    assert fake.ran("git branch -D release/v1.7.0")
    assert fake.ran("git push origin --delete release/v1.7.0") is pushed
    retry = _install(monkeypatch, FakeProcs())
    again = runner.invoke(app, ["release"])
    assert again.exit_code == 0, again.output
    assert retry.ran("gh pr create")


def test_missing_executable_still_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs())
    fake.raises["cz bump --yes"] = FileNotFoundError("cz")
    result = runner.invoke(app, ["release"])
    assert result.exit_code != 0
    assert isinstance(result.exception, FileNotFoundError)
    assert fake.ran("git checkout main")
    assert fake.ran("git branch -D release/v1.7.0")


def test_refuses_when_remote_check_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs(**{"git ls-remote --exit-code --heads origin": (128, "")}))
    result = runner.invoke(app, ["release"])
    assert result.exit_code == 1
    assert "could not check origin for release/v1.7.0 (git ls-remote exit 128)" in result.output
    assert not fake.ran("git checkout -b")


def test_failed_bump_deletes_tag_it_created(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs(**{"cz bump --yes": (1, "")}))
    fake.bump_creates_tag = True
    result = runner.invoke(app, ["release"])
    assert result.exit_code == 1
    assert fake.ran("git tag -d v1.7.0")


def test_rollback_without_tag_does_not_delete_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, FakeProcs(**{"cz bump --yes": (1, "")}))
    runner.invoke(app, ["release"])
    assert not fake.ran("git tag -d")


def test_dry_run_body_passes_pr_body_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, FakeProcs())
    result = runner.invoke(app, ["release", "--dry-run"])
    assert result.exit_code == 0, result.output
    body = result.output.split("PR title: release: v1.7.0\n", 1)[1].strip()
    monkeypatch.undo()  # the validator spawns its own check script via the real subprocess.run
    check = run_pr_body_validation(body, ["pyproject.toml", "uv.lock", "CHANGELOG.md"], PROJECT_ROOT)
    assert check is not None
    assert check.passed, check.output


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
    assert fake.ran("git branch -D release/v1.7.0")
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

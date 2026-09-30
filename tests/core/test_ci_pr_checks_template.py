"""Tests for the ydk-pr-checks.yml CI template."""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest
import yaml

from ydk.core.ci_generator import TEMPLATES_DIR, CiContext, render

CTX = CiContext(
    version="1.5.0",
    stack="python-cli",
    spec_location="docs/specs",
    components_path=".ydk/components",
    schemas_path=".ydk/schemas",
)


def _workflow() -> dict:
    text = render((TEMPLATES_DIR / "ydk-pr-checks.yml").read_text(encoding="utf-8"), CTX)
    return yaml.safe_load(text)


def _triggers(wf: dict) -> dict:
    # PyYAML parses the bare key `on` as boolean True.
    return wf.get("on") or wf[True]


def test_trigger_and_permissions() -> None:
    wf = _workflow()
    assert _triggers(wf)["pull_request"]["types"] == ["opened", "synchronize", "reopened"]
    assert wf["permissions"] == {"contents": "read"}
    assert "cancel-in-progress" in wf["concurrency"]


def test_branch_name_passes_ref_via_env() -> None:
    job = _workflow()["jobs"]["branch-name"]
    step = job["steps"][0]
    assert step["env"]["BRANCH"] == "${{ github.head_ref }}"
    assert "github.head_ref" not in step["run"]


def test_commit_messages_job() -> None:
    steps = _workflow()["jobs"]["commit-messages"]["steps"]
    assert steps[0]["uses"] == "actions/checkout@v4"
    assert steps[0]["with"]["fetch-depth"] == 0
    assert steps[1]["uses"] == "astral-sh/setup-uv@v7"
    run = steps[2]["run"]
    assert "cz check" in run
    assert "commitizen>=4,<5" in run
    assert '"origin/${BASE_REF}...HEAD"' in run
    assert steps[2]["env"]["BASE_REF"] == "${{ github.base_ref }}"


@pytest.mark.parametrize(
    ("branch", "ok"),
    [("feat/add-x", True), ("task/276-y", True), ("main", False), ("feat/Bad_Name", False)],
)
def test_branch_regex(branch: str, ok: bool) -> None:
    run = _workflow()["jobs"]["branch-name"]["steps"][0]["run"]
    pattern = re.search(r"grep -qE '([^']+)'", run)
    assert pattern
    assert bool(re.match(pattern.group(1), branch)) is ok


@pytest.mark.skipif(shutil.which("uvx") is None or shutil.which("git") is None, reason="needs uvx and git")
def test_cz_check_without_commitizen_config(tmp_path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    git("commit", "-q", "--allow-empty", "-m", "chore: init")
    git("checkout", "-q", "-b", "feat/x")
    git("commit", "-q", "--allow-empty", "-m", "feat: add thing")
    proc = subprocess.run(
        ["uvx", "--from", "commitizen>=4,<5", "cz", "check", "--rev-range", "main...HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr

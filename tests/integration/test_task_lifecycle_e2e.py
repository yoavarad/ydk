"""E2E test for full task lifecycle using a real GitHub test repo.

Exercises: issue create → task start → commit → task done → PR created on GitHub.

Requires:
- gh CLI authenticated
- GitHub repo configured via YDK_TASK_LIFECYCLE_TEST_REPO accessible
"""

from __future__ import annotations

import json
import os
import subprocess
import time

import pytest

REAL_REPO = os.environ.get("YDK_TASK_LIFECYCLE_TEST_REPO", "example-org/ydk-task-lifecycle-test")


def _gh_available() -> bool:
    """Check if gh CLI can access the test repo."""
    try:
        result = subprocess.run(
            ["gh", "repo", "view", REAL_REPO],
            capture_output=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _gh_available(), reason=f"Cannot access {REAL_REPO}"),
]


@pytest.fixture
def e2e_project(tmp_path):
    """Clone the real test repo and set up YDK structure."""
    project = tmp_path / "e2e-lifecycle"
    subprocess.run(
        ["gh", "repo", "clone", REAL_REPO, str(project)],
        capture_output=True,
        check=True,
    )

    # Create a unique base branch
    base_branch = f"test/base-{int(time.time())}"
    subprocess.run(
        ["git", "checkout", "-b", base_branch],
        cwd=str(project),
        capture_output=True,
        check=True,
    )

    # Set up minimal YDK structure
    ydk_dir = project / ".ydk"
    ydk_dir.mkdir(exist_ok=True)
    (ydk_dir / "config.yaml").write_text("project:\n  name: e2e-test\n  remote: github\n  stack: python-fastapi\n")
    (ydk_dir / "todos.yaml").write_text("todos: {}\nnext_id: 1\n")

    # Initial commit + push the base branch so the task branch can PR against it
    subprocess.run(["git", "add", "."], cwd=str(project), capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "chore: setup ydk structure for e2e test"],
        cwd=str(project),
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", base_branch],
        cwd=str(project),
        capture_output=True,
        check=True,
    )

    cleanup_branches = [base_branch]
    cleanup_prs: list[str] = []
    cleanup_issues: list[str] = []

    yield {
        "project": project,
        "base_branch": base_branch,
        "cleanup_branches": cleanup_branches,
        "cleanup_prs": cleanup_prs,
        "cleanup_issues": cleanup_issues,
    }

    # Cleanup: close PRs, issues, delete remote branches
    for pr_num in cleanup_prs:
        subprocess.run(
            ["gh", "pr", "close", pr_num],
            cwd=str(project),
            capture_output=True,
        )
    for issue_num in cleanup_issues:
        subprocess.run(
            ["gh", "issue", "close", issue_num],
            cwd=str(project),
            capture_output=True,
        )
    for branch in cleanup_branches:
        subprocess.run(
            ["git", "push", "origin", "--delete", branch],
            cwd=str(project),
            capture_output=True,
        )


class TestFullTaskLifecycle:
    """Test that ydk task start → implement → done creates a real PR."""

    def test_task_done_creates_github_pr(self, e2e_project, monkeypatch):
        """The complete lifecycle creates a real GitHub PR with correct base branch."""
        from ydk.core.events import EventBus
        from ydk.core.git_worktree import WorktreeManager
        from ydk.core.task_lifecycle import TaskLifecycle
        from ydk.core.verifier import Verifier
        from ydk.repositories.github.tasks import GitHubTaskRepository

        project = e2e_project["project"]
        base_branch = e2e_project["base_branch"]

        # Step 1: Create a GitHub issue (simulates task creation)
        result = subprocess.run(
            [
                "gh",
                "issue",
                "create",
                "--title",
                f"E2E lifecycle test {int(time.time())}",
                "--body",
                "Automated integration test for task lifecycle",
            ],
            cwd=str(project),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Issue creation failed: {result.stderr}"
        issue_url = result.stdout.strip()
        issue_number = issue_url.split("/")[-1]
        e2e_project["cleanup_issues"].append(issue_number)

        # Step 2: Set up TaskLifecycle with the real GitHub-backed repository.
        # GitHubTaskRepository shells out to the gh CLI, which infers the
        # target repo from the git remote of the current working directory,
        # so point the process at the cloned e2e project for the duration
        # of the test (gh CLI itself is the allowed system boundary here).
        monkeypatch.chdir(project)
        repo = GitHubTaskRepository()

        lifecycle = TaskLifecycle(
            repo=repo,
            events=EventBus(),
            worktree_mgr=WorktreeManager(project),
            verifier=Verifier(project_root=project, enabled_plugins=[]),
            project_root=project,
            worktree_isolation=False,
        )

        # Step 3: Start task (creates branch from base_branch)
        start_result = lifecycle.start(issue_number, base_branch=base_branch)
        assert "worktree" in start_result or "branch" in start_result

        # Verify active-task.json was written
        active_task_file = project / ".ydk" / "active-task.json"
        assert active_task_file.exists(), "active-task.json not created"
        task_ctx = json.loads(active_task_file.read_text())
        assert task_ctx["base_branch"] == base_branch
        assert task_ctx["task_id"] == issue_number

        # Verify we're on the correct branch
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(project),
            capture_output=True,
            text=True,
        )
        actual_branch = branch_result.stdout.strip()
        assert actual_branch.startswith(f"task/{issue_number}")
        e2e_project["cleanup_branches"].append(actual_branch)

        # Step 4: Make a change and commit
        test_file = project / "test_lifecycle_file.py"
        test_file.write_text("# E2E lifecycle test file\nprint('hello from lifecycle test')\n")
        subprocess.run(["git", "add", "."], cwd=str(project), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "feat: e2e test change for lifecycle"],
            cwd=str(project),
            capture_output=True,
            check=True,
        )

        # Step 5: Run task done
        done_result = lifecycle.done(issue_number)

        # Step 6: Verify PR was created (not local:// fallback)
        assert done_result["passed"] is True, f"Task done reported failure: {done_result}"
        pr_url = done_result.get("pr_url", "")
        assert "local://" not in pr_url, f"PR creation fell back to local: {pr_url}"
        assert "github.com" in pr_url or "pull" in pr_url, f"Expected GitHub PR URL, got: {pr_url}"

        # Step 7: Verify PR exists on GitHub with correct metadata
        pr_number = pr_url.split("/")[-1]
        e2e_project["cleanup_prs"].append(pr_number)

        check = subprocess.run(
            ["gh", "pr", "view", pr_number, "--json", "title,state,baseRefName,headRefName"],
            cwd=str(project),
            capture_output=True,
            text=True,
        )
        assert check.returncode == 0, f"PR not found on GitHub: {check.stderr}"
        pr_data = json.loads(check.stdout)

        # PR targets the correct base branch (not main)
        assert pr_data["baseRefName"] == base_branch, f"PR base is '{pr_data['baseRefName']}', expected '{base_branch}'"
        # PR head branch matches actual branch
        assert pr_data["headRefName"] == actual_branch, (
            f"PR head is '{pr_data['headRefName']}', expected '{actual_branch}'"
        )
        # PR title contains task ID
        assert f"Task {issue_number}" in pr_data["title"]

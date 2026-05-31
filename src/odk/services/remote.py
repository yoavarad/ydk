"""Remote service implementations — GitHub and GitLab via their CLIs."""

from __future__ import annotations

import json
import subprocess


class GitHubRemoteService:
    """GitHub operations via gh CLI."""

    def create_issue(self, title: str, body: str, labels: list[str], milestone: str | None = None) -> str:
        """Create a GitHub issue and return its URL."""
        cmd: list[str] = ["gh", "issue", "create", "--title", title, "--body", body]
        for label in labels:
            cmd.extend(["--label", label])
        if milestone:
            cmd.extend(["--milestone", milestone])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            msg = f"Failed to create issue: {result.stderr.strip()}"
            raise RuntimeError(msg)
        return result.stdout.strip()

    def list_issues(
        self, milestone: str | None = None, labels: list[str] | None = None, state: str = "open"
    ) -> list[dict]:
        """List issues with optional filters."""
        cmd: list[str] = ["gh", "issue", "list", "--json", "number,title,state,labels,body", "--state", state]
        if milestone:
            cmd.extend(["--milestone", milestone])
        if labels:
            for label in labels:
                cmd.extend(["--label", label])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return []
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

    def add_label(self, issue_number: int, label: str) -> None:
        """Add a label to an issue."""
        cmd = ["gh", "issue", "edit", str(issue_number), "--add-label", label]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            msg = f"Failed to add label: {result.stderr.strip()}"
            raise RuntimeError(msg)

    def add_comment(self, issue_number: int, comment: str) -> None:
        """Add a comment to an issue."""
        cmd = ["gh", "issue", "comment", str(issue_number), "--body", comment]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            msg = f"Failed to add comment: {result.stderr.strip()}"
            raise RuntimeError(msg)


class GitLabRemoteService:
    """GitLab operations via glab CLI."""

    def create_issue(self, title: str, body: str, labels: list[str], milestone: str | None = None) -> str:
        """Create a GitLab issue and return its URL."""
        cmd: list[str] = ["glab", "issue", "create", "--title", title, "--description", body]
        if labels:
            cmd.extend(["--label", ",".join(labels)])
        if milestone:
            cmd.extend(["--milestone", milestone])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            msg = f"Failed to create issue: {result.stderr.strip()}"
            raise RuntimeError(msg)
        return result.stdout.strip()

    def list_issues(
        self, milestone: str | None = None, labels: list[str] | None = None, state: str = "open"
    ) -> list[dict]:
        """List issues with optional filters."""
        # glab uses 'opened' not 'open'
        glab_state = "opened" if state == "open" else state
        cmd: list[str] = ["glab", "issue", "list", "--output", "json", "--state", glab_state]
        if milestone:
            cmd.extend(["--milestone", milestone])
        if labels:
            cmd.extend(["--label", ",".join(labels)])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return []
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

    def add_label(self, issue_number: int, label: str) -> None:
        """Add a label to an issue."""
        cmd = ["glab", "issue", "update", str(issue_number), "--label", label]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            msg = f"Failed to add label: {result.stderr.strip()}"
            raise RuntimeError(msg)

    def add_comment(self, issue_number: int, comment: str) -> None:
        """Add a comment to an issue."""
        cmd = ["glab", "issue", "note", str(issue_number), "--message", comment]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            msg = f"Failed to add comment: {result.stderr.strip()}"
            raise RuntimeError(msg)

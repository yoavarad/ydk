"""Remote service implementations — GitHub and GitLab via their CLIs."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import yaml

from ydk.repositories.github._helpers import GH_LIST_LIMIT
from ydk.repositories.gitlab._helpers import glab_state_flags, list_glab_issues

_MR_URL_RE = re.compile(r"https?://\S+?/-/merge_requests/\d+")
# glab MR states -> the GitHub PR states the rest of ydk compares against.
_MR_STATE_MAP = {"opened": "OPEN", "merged": "MERGED", "closed": "CLOSED"}


def _run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def is_gitlab_remote(config_path: Path = Path(".ydk/config.yaml")) -> bool:
    """True when ``project.remote`` is gitlab. An unreadable config keeps the default (GitHub/gh) path."""
    from ydk.core.config import load_config

    try:
        return load_config(config_path).project.remote == "gitlab"
    except (OSError, ValueError, yaml.YAMLError):
        return False


def _split_mr_url(mr_url: str) -> tuple[str, str] | None:
    """Split ``https://host/group/proj/-/merge_requests/7[/diffs|?q|#n]`` into (project URL, iid)."""
    match = re.fullmatch(r"(https?://\S+?)/-/merge_requests/(\d+)(?:[/?#]\S*)?", mr_url.strip())
    if match is None:
        return None
    return match.group(1), match.group(2)


class GitHubRemoteService:
    """GitHub operations via gh CLI."""

    def create_issue(self, title: str, body: str, labels: list[str], milestone: str | None = None) -> str:
        """Create a GitHub issue and return its URL."""
        cmd: list[str] = ["gh", "issue", "create", "--title", title, "--body", body]
        for label in labels:
            cmd.extend(["--label", label])
        if milestone:
            cmd.extend(["--milestone", milestone])

        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            msg = f"Failed to create issue: {result.stderr.strip()}"
            raise RuntimeError(msg)
        return result.stdout.strip()

    def list_issues(
        self, milestone: str | None = None, labels: list[str] | None = None, state: str = "open"
    ) -> list[dict]:
        """List issues with optional filters."""
        cmd: list[str] = [
            "gh",
            "issue",
            "list",
            "--json",
            "number,title,state,labels,body",
            "--state",
            state,
            "--limit",
            str(GH_LIST_LIMIT),
        ]
        if milestone:
            cmd.extend(["--milestone", milestone])
        if labels:
            for label in labels:
                cmd.extend(["--label", label])

        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            return []
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

    def add_label(self, issue_number: int, label: str) -> None:
        """Add a label to an issue."""
        cmd = ["gh", "issue", "edit", str(issue_number), "--add-label", label]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            msg = f"Failed to add label: {result.stderr.strip()}"
            raise RuntimeError(msg)

    def add_comment(self, issue_number: int, comment: str) -> None:
        """Add a comment to an issue."""
        cmd = ["gh", "issue", "comment", str(issue_number), "--body", comment]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
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

        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            msg = f"Failed to create issue: {result.stderr.strip()}"
            raise RuntimeError(msg)
        return result.stdout.strip()

    def list_issues(
        self, milestone: str | None = None, labels: list[str] | None = None, state: str = "open"
    ) -> list[dict]:
        """List issues with optional filters."""
        cmd: list[str] = ["glab", "issue", "list", "--output", "json", *glab_state_flags(state)]
        if milestone:
            cmd.extend(["--milestone", milestone])
        if labels:
            cmd.extend(["--label", ",".join(labels)])

        return list_glab_issues(
            lambda c: subprocess.run(c, capture_output=True, text=True, encoding="utf-8", errors="replace"), cmd
        )

    def add_label(self, issue_number: int, label: str) -> None:
        """Add a label to an issue."""
        cmd = ["glab", "issue", "update", str(issue_number), "--label", label]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            msg = f"Failed to add label: {result.stderr.strip()}"
            raise RuntimeError(msg)

    def add_comment(self, issue_number: int, comment: str) -> None:
        """Add a comment to an issue."""
        cmd = ["glab", "issue", "note", str(issue_number), "--message", comment]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            msg = f"Failed to add comment: {result.stderr.strip()}"
            raise RuntimeError(msg)

    def create_merge_request(
        self, title: str, description_file: str, source_branch: str, target_branch: str, cwd: str | None = None
    ) -> str:
        """Open an MR via ``glab mr create`` and return its URL."""
        cmd = [
            "glab",
            "mr",
            "create",
            "--title",
            title,
            "--description-file",
            description_file,
            "--source-branch",
            source_branch,
            "--target-branch",
            target_branch,
            "--yes",
        ]
        result = _run(cmd, cwd=cwd)
        if result.returncode != 0:
            stderr = result.stderr.strip() if result.stderr else ""
            msg = f"glab mr create failed: {stderr or 'no error output captured'}"
            raise RuntimeError(msg)
        urls = _MR_URL_RE.findall(result.stdout or "")
        if not urls:
            msg = "glab mr create succeeded but printed no MR URL"
            raise RuntimeError(msg)
        return urls[-1]

    def find_merge_request_iid(self, source_branch: str) -> str | None:
        """Return the IID of the newest MR (any state) from *source_branch*, or None."""
        result = _run(["glab", "mr", "list", "--source-branch", source_branch, "--all", "--output", "json"])
        if result.returncode != 0:
            return None
        try:
            mrs = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        if not isinstance(mrs, list) or not mrs:
            return None
        iid = mrs[0].get("iid") if isinstance(mrs[0], dict) else None
        return str(iid) if iid is not None else None

    def merge_request_state(self, mr_url: str) -> str | None:
        """Return the MR state as a GitHub PR state (OPEN/MERGED/CLOSED), or None on failure."""
        parts = _split_mr_url(mr_url)
        if parts is None:
            return None
        project, iid = parts
        result = _run(["glab", "mr", "view", iid, "--repo", project, "--output", "json"])
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict) or "state" not in data:
            return None
        state = str(data["state"])
        return _MR_STATE_MAP.get(state, state.upper())

    def add_merge_request_note(self, mr_url: str, body: str) -> None:
        """Add a comment (note) to the MR at *mr_url*."""
        parts = _split_mr_url(mr_url)
        if parts is None:
            msg = f"Not a GitLab merge request URL: {mr_url}"
            raise ValueError(msg)
        project, iid = parts
        result = _run(["glab", "mr", "note", "create", iid, "--repo", project, "--message", body])
        if result.returncode != 0:
            msg = f"Failed to add MR note: {result.stderr.strip()}"
            raise RuntimeError(msg)

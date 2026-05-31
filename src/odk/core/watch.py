"""Watch manager — polls GitHub PRs for new review comments and resumes Claude Code sessions."""

from __future__ import annotations

import fcntl
import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("odk.watch")


class WatchManager:
    """Manage session tracking and PR comment polling."""

    def __init__(self, project_root: Path) -> None:
        self._root = project_root.resolve()
        self._sessions_file = self._root / ".odk" / "sessions.yaml"
        self._lock_path = self._root / ".odk" / "watch.lock"
        self._lock_file: Any = None

    # -- Session tracking --

    def record_session(self, task_id: str, session_id: str, branch: str) -> None:
        """Record a Claude Code session for a task."""
        sessions = self._load_sessions()
        sessions[task_id] = {
            "session_id": session_id,
            "branch": branch,
            "last_polled": None,
            "status": "open",
        }
        self._save_sessions(sessions)

    def record_pr(self, task_id: str, pr_number: int) -> None:
        """Record the PR number for a task session."""
        sessions = self._load_sessions()
        if task_id not in sessions:
            logger.warning("No session recorded for task %s — skipping PR recording", task_id)
            return
        sessions[task_id]["pr_number"] = pr_number
        self._save_sessions(sessions)

    def mark_done(self, task_id: str) -> None:
        """Mark a session as done (no longer polling)."""
        sessions = self._load_sessions()
        if task_id in sessions:
            sessions[task_id]["status"] = "done"
            self._save_sessions(sessions)

    # -- Polling --

    def poll(self) -> list[dict[str, Any]]:
        """Check all active sessions for new PR review comments.

        Returns list of dicts with keys: task_id, session_id, pr_number, comments.
        """
        sessions = self._load_sessions()
        results: list[dict[str, Any]] = []

        for task_id, info in sessions.items():
            if info.get("status") != "open" or not info.get("pr_number"):
                continue

            new_comments = self._fetch_new_comments(
                info["pr_number"],
                info.get("last_polled"),
            )
            if new_comments:
                results.append(
                    {
                        "task_id": task_id,
                        "session_id": info["session_id"],
                        "pr_number": info["pr_number"],
                        "comments": new_comments,
                    }
                )

            info["last_polled"] = datetime.now(UTC).isoformat()

        self._save_sessions(sessions)
        return results

    _AGENT_MARKER = "<!-- odk-agent-reply -->"

    def _fetch_new_comments(self, pr_number: int, since: str | None) -> list[dict[str, Any]]:
        """Fetch review comments, issue comments, and reviews newer than *since*.

        Skips comments that contain the ``<!-- odk-agent-reply -->`` marker
        (posted by the agent itself) to prevent triggering loops.
        Also reacts with 👀 to each new comment so the reviewer knows it was seen.
        """
        comments: list[dict[str, Any]] = []

        # 1. Pull request review comments (inline code comments)
        cmd = ["gh", "api", f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/comments", "--jq", "."]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            try:
                for c in json.loads(result.stdout):
                    created = c.get("created_at", "")
                    if since and created <= since:
                        continue
                    body = c.get("body", "")
                    if self._AGENT_MARKER in body:
                        continue
                    comments.append(
                        {
                            "path": c.get("path", ""),
                            "line": c.get("line") or c.get("original_line"),
                            "body": body,
                            "author": c.get("user", {}).get("login", "unknown"),
                            "created_at": created,
                            "comment_id": c.get("id"),
                            "comment_type": "pr_review_comment",
                        }
                    )
            except json.JSONDecodeError:
                logger.warning("Failed to parse PR comments JSON for PR #%d", pr_number)

        # 2. Issue comments (top-level PR comments from gh pr comment)
        issue_cmd = ["gh", "api", f"repos/{{owner}}/{{repo}}/issues/{pr_number}/comments", "--jq", "."]
        result = subprocess.run(issue_cmd, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            try:
                for c in json.loads(result.stdout):
                    created = c.get("created_at", "")
                    if since and created <= since:
                        continue
                    body = c.get("body", "")
                    if not body or not body.strip():
                        continue
                    if self._AGENT_MARKER in body:
                        continue
                    comments.append(
                        {
                            "path": "(comment)",
                            "line": None,
                            "body": body,
                            "author": c.get("user", {}).get("login", "unknown"),
                            "created_at": created,
                            "comment_id": c.get("id"),
                            "comment_type": "issue_comment",
                        }
                    )
            except json.JSONDecodeError:
                logger.warning("Failed to parse issue comments JSON for PR #%d", pr_number)

        # 3. Top-level review bodies (approve/request-changes/comment reviews)
        reviews_cmd = ["gh", "api", f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/reviews", "--jq", "."]
        result = subprocess.run(reviews_cmd, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            try:
                for r in json.loads(result.stdout):
                    body = r.get("body", "")
                    if not body or not body.strip():
                        continue
                    if self._AGENT_MARKER in body:
                        continue
                    submitted = r.get("submitted_at", "")
                    if since and submitted <= since:
                        continue
                    comments.append(
                        {
                            "path": "(review)",
                            "line": None,
                            "body": body,
                            "author": r.get("user", {}).get("login", "unknown"),
                            "created_at": submitted,
                            "comment_id": r.get("id"),
                            "comment_type": "review",
                        }
                    )
            except json.JSONDecodeError:
                logger.warning("Failed to parse PR reviews JSON for PR #%d", pr_number)

        # React 👀 to each new comment so the reviewer knows it was seen
        for c in comments:
            self._react_eyes(c.get("comment_id"), c.get("comment_type"), pr_number)

        return comments

    def _react_eyes(self, comment_id: int | None, comment_type: str | None, pr_number: int) -> None:
        """Add 👀 reaction to a comment."""
        if not comment_id:
            return
        if comment_type == "issue_comment":
            endpoint = f"repos/{{owner}}/{{repo}}/issues/comments/{comment_id}/reactions"
        elif comment_type == "pr_review_comment":
            endpoint = f"repos/{{owner}}/{{repo}}/pulls/comments/{comment_id}/reactions"
        else:
            return  # Reviews don't support reactions on the review itself
        try:
            subprocess.run(
                ["gh", "api", "-X", "POST", endpoint, "-f", "content=eyes"],
                capture_output=True,
                text=True,
            )
            logger.info("Reacted 👀 to %s #%d on PR #%d", comment_type, comment_id, pr_number)
        except Exception:
            logger.warning("Failed to react to comment %d on PR #%d", comment_id, pr_number)

    # -- Agent triggering --

    def trigger_agent(self, session_id: str, project_dir: str, message: str) -> None:
        """Resume a Claude Code session with a message (fire and forget).

        Uses ``--dangerously-skip-permissions`` so the agent can execute
        commands (gh, git, etc.) without interactive approval prompts.
        """
        cmd = [
            "claude",
            "--resume",
            session_id,
            "--dangerously-skip-permissions",
            "-p",
            message,
        ]
        logger.info("Triggering agent for session %s in %s", session_id, project_dir)
        subprocess.Popen(cmd, cwd=project_dir, start_new_session=True)

    # -- Lock file --

    def acquire_lock(self) -> bool:
        """Acquire an exclusive lock to prevent concurrent polls.

        Returns True if lock acquired, False if another poll is running.
        """
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_file = open(self._lock_path, "w")  # noqa: SIM115
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self._lock_file.close()
            self._lock_file = None
            return False

    def release_lock(self) -> None:
        """Release the poll lock."""
        if self._lock_file is not None:
            fcntl.flock(self._lock_file, fcntl.LOCK_UN)
            self._lock_file.close()
            self._lock_file = None

    # -- Session file I/O --

    def _load_sessions(self) -> dict[str, Any]:
        """Load sessions from YAML file."""
        if not self._sessions_file.is_file():
            return {}
        content = self._sessions_file.read_text(encoding="utf-8")
        data = yaml.safe_load(content) or {}
        return data.get("sessions", {})

    def _save_sessions(self, sessions: dict[str, Any]) -> None:
        """Save sessions to YAML file."""
        self._sessions_file.parent.mkdir(parents=True, exist_ok=True)
        self._sessions_file.write_text(
            yaml.dump({"sessions": sessions}, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    # -- LaunchAgent plist --

    def generate_plist(self, label: str | None = None) -> str:
        """Generate a macOS LaunchAgent plist for periodic polling."""
        import shutil

        project_name = self._root.name
        plist_label = label or f"com.odk.watch.{project_name}"

        odk_path = shutil.which("odk") or "/usr/local/bin/odk"
        env_path = _get_env_path()

        log_dir = self._root / ".odk" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{plist_label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{odk_path}</string>
        <string>watch</string>
        <string>poll</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{self._root}</string>
    <key>StartInterval</key>
    <integer>30</integer>
    <key>StandardOutPath</key>
    <string>{log_dir}/watch-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/watch-stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{env_path}</string>
    </dict>
</dict>
</plist>"""

    def plist_path(self) -> Path:
        """Return the path where the LaunchAgent plist would be installed."""
        project_name = self._root.name
        return Path.home() / "Library" / "LaunchAgents" / f"com.odk.watch.{project_name}.plist"

    def get_active_sessions(self) -> dict[str, Any]:
        """Return all sessions (for status display)."""
        return self._load_sessions()

    def last_poll_time(self) -> str | None:
        """Return the most recent last_polled timestamp across all sessions."""
        sessions = self._load_sessions()
        times = [info.get("last_polled") for info in sessions.values() if info.get("last_polled")]
        return max(times) if times else None


def _get_env_path() -> str:
    """Get the current PATH for embedding in the plist."""
    import os

    return os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")

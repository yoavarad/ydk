"""Post verification results as PR comments via gh CLI."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odk.models.verification import VerificationReport

MARKER = "<!-- odk-verification -->"


class PRCommenter:
    """Posts or updates a PR comment with verification results."""

    def post_verification_results(self, pr_url: str, report: VerificationReport) -> None:
        """Post or update a PR comment with verification results.

        If a previous ODK comment exists (identified by hidden marker),
        updates it instead of creating a new one.
        """
        body = self.format_comment(report)
        existing_id = self._find_existing_comment(pr_url)
        if existing_id is not None:
            self._update_comment(existing_id, body)
        else:
            self._create_comment(pr_url, body)

    def format_comment(self, report: VerificationReport) -> str:
        """Format a verification report as a markdown PR comment."""
        lines: list[str] = [MARKER, ""]

        # Header
        icon = ":white_check_mark:" if report.all_passed else ":x:"
        status = "ALL PASSED" if report.all_passed else "FAILED"
        lines.append(f"## {icon} ODK Verification — {status}")
        lines.append("")

        # Table
        lines.append("| Check | Status | Duration |")
        lines.append("|-------|--------|----------|")
        for check in report.checks:
            check_icon = ":white_check_mark:" if check.passed else ":x:"
            lines.append(f"| {check.name} | {check_icon} | {check.duration_seconds}s |")
        lines.append("")

        # Summary
        total = len(report.checks)
        passed = sum(1 for c in report.checks if c.passed)
        lines.append(f"**{passed}/{total}** checks passed in **{report.total_duration_seconds}s**")
        lines.append("")
        lines.append(f"_Timestamp: {report.timestamp}_")

        return "\n".join(lines)

    def _find_existing_comment(self, pr_url: str) -> str | None:
        """Find an existing ODK verification comment on the PR.

        Returns the comment node ID if found, None otherwise.
        """
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                pr_url,
                "--json",
                "comments",
                "--jq",
                ".comments",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None

        comments: list[dict[str, str]] = json.loads(result.stdout)
        for comment in comments:
            if MARKER in comment.get("body", ""):
                return comment["id"]
        return None

    def _create_comment(self, pr_url: str, body: str) -> None:
        """Create a new comment on the PR."""
        result = subprocess.run(
            ["gh", "pr", "comment", pr_url, "--body", body],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create PR comment: {result.stderr}")

    def _update_comment(self, comment_id: str, body: str) -> None:
        """Update an existing comment using the GitHub GraphQL API."""
        query = """
        mutation($id: ID!, $body: String!) {
          updateIssueComment(input: {id: $id, body: $body}) {
            issueComment { id }
          }
        }
        """
        result = subprocess.run(
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-f",
                f"id={comment_id}",
                "-f",
                f"body={body}",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to update PR comment: {result.stderr}")

"""Tests for PR commenting — formatting, marker detection, create/update logic."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
import yaml

from odk.core.pr_commenter import PRCommenter
from odk.models.verification import CheckResult, VerificationReport

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MARKER = "<!-- odk-verification -->"


def _sample_report(*, all_passed: bool = True) -> VerificationReport:
    checks = [
        CheckResult(
            name="lint-ruff",
            passed=True,
            output="ok",
            duration_seconds=0.3,
        ),
        CheckResult(
            name="tests-pytest",
            passed=all_passed,
            output="FAILED" if not all_passed else "12 passed",
            duration_seconds=1.7,
        ),
    ]
    return VerificationReport(
        timestamp="2026-04-28T12:00:00Z",
        checks=checks,
        all_passed=all_passed,
        total_duration_seconds=2.0,
    )


# ---------------------------------------------------------------------------
# Comment formatting
# ---------------------------------------------------------------------------


class TestFormatComment:
    def test_contains_hidden_marker(self) -> None:
        commenter = PRCommenter()
        report = _sample_report()
        comment = commenter.format_comment(report)
        assert MARKER in comment

    def test_contains_check_table(self) -> None:
        commenter = PRCommenter()
        report = _sample_report()
        comment = commenter.format_comment(report)
        assert "lint-ruff" in comment
        assert "tests-pytest" in comment
        assert "| Check" in comment

    def test_passed_icon(self) -> None:
        commenter = PRCommenter()
        report = _sample_report(all_passed=True)
        comment = commenter.format_comment(report)
        # 2 checks + 1 header = 3 total checkmark icons
        assert comment.count(":white_check_mark:") == 3

    def test_failed_icon(self) -> None:
        commenter = PRCommenter()
        report = _sample_report(all_passed=False)
        comment = commenter.format_comment(report)
        assert ":x:" in comment

    def test_summary_line_all_passed(self) -> None:
        commenter = PRCommenter()
        report = _sample_report(all_passed=True)
        comment = commenter.format_comment(report)
        assert "ALL PASSED" in comment

    def test_summary_line_failed(self) -> None:
        commenter = PRCommenter()
        report = _sample_report(all_passed=False)
        comment = commenter.format_comment(report)
        assert "FAILED" in comment

    def test_contains_timestamp(self) -> None:
        commenter = PRCommenter()
        report = _sample_report()
        comment = commenter.format_comment(report)
        assert "2026-04-28T12:00:00Z" in comment

    def test_contains_duration(self) -> None:
        commenter = PRCommenter()
        report = _sample_report()
        comment = commenter.format_comment(report)
        assert "0.3" in comment
        assert "1.7" in comment


# ---------------------------------------------------------------------------
# Marker detection
# ---------------------------------------------------------------------------


class TestMarkerDetection:
    def test_finds_existing_comment_id(self) -> None:
        commenter = PRCommenter()
        comments_json = (
            '[{"id": "IC_abc123", "body": "some text ' + MARKER + ' more text"},'
            ' {"id": "IC_other", "body": "unrelated comment"}]'
        )
        with patch("odk.core.pr_commenter.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=comments_json,
            )
            comment_id = commenter._find_existing_comment("https://github.com/org/repo/pull/42")
            assert comment_id == "IC_abc123"

    def test_returns_none_when_no_marker(self) -> None:
        commenter = PRCommenter()
        comments_json = '[{"id": "IC_other", "body": "unrelated comment"}]'
        with patch("odk.core.pr_commenter.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=comments_json,
            )
            comment_id = commenter._find_existing_comment("https://github.com/org/repo/pull/42")
            assert comment_id is None

    def test_returns_none_on_empty_comments(self) -> None:
        commenter = PRCommenter()
        with patch("odk.core.pr_commenter.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="[]",
            )
            comment_id = commenter._find_existing_comment("https://github.com/org/repo/pull/42")
            assert comment_id is None


# ---------------------------------------------------------------------------
# Create vs update logic
# ---------------------------------------------------------------------------


class TestPostVerificationResults:
    def test_creates_new_comment_when_no_existing(self) -> None:
        commenter = PRCommenter()
        report = _sample_report()
        pr_url = "https://github.com/org/repo/pull/42"

        with (
            patch.object(commenter, "_find_existing_comment", return_value=None),
            patch("odk.core.pr_commenter.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            commenter.post_verification_results(pr_url, report)

            mock_run.assert_called_once()
            call_args = mock_run.call_args
            cmd = call_args[0][0]
            assert "gh" in cmd
            assert "pr" in cmd
            assert "comment" in cmd
            assert pr_url in cmd

    def test_updates_existing_comment(self) -> None:
        commenter = PRCommenter()
        report = _sample_report()
        pr_url = "https://github.com/org/repo/pull/42"

        with (
            patch.object(commenter, "_find_existing_comment", return_value="IC_abc123"),
            patch("odk.core.pr_commenter.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            commenter.post_verification_results(pr_url, report)

            mock_run.assert_called_once()
            call_args = mock_run.call_args
            cmd = call_args[0][0]
            assert "gh" in cmd
            assert "api" in cmd
            assert any("IC_abc123" in str(a) for a in call_args[0])


# ---------------------------------------------------------------------------
# Subprocess call correctness
# ---------------------------------------------------------------------------


class TestSubprocessCalls:
    def test_create_uses_gh_pr_comment(self) -> None:
        commenter = PRCommenter()
        body = "test comment"
        pr_url = "https://github.com/org/repo/pull/42"

        with patch("odk.core.pr_commenter.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            commenter._create_comment(pr_url, body)

            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert cmd == ["gh", "pr", "comment", pr_url, "--body", body]

    def test_update_uses_gh_api(self) -> None:
        commenter = PRCommenter()
        body = "updated comment"

        with patch("odk.core.pr_commenter.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            commenter._update_comment("IC_abc123", body)

            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert "gh" in cmd
            assert "api" in cmd

    def test_create_raises_on_failure(self) -> None:
        commenter = PRCommenter()
        pr_url = "https://github.com/org/repo/pull/42"

        with patch("odk.core.pr_commenter.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="auth error")
            with pytest.raises(RuntimeError, match="Failed to create PR comment"):
                commenter._create_comment(pr_url, "body")

    def test_update_raises_on_failure(self) -> None:
        commenter = PRCommenter()

        with patch("odk.core.pr_commenter.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="not found")
            with pytest.raises(RuntimeError, match="Failed to update PR comment"):
                commenter._update_comment("IC_abc123", "body")


# ---------------------------------------------------------------------------
# on_complete callback in Verifier.run_all
# ---------------------------------------------------------------------------


class TestOnCompleteCallback:
    def test_callback_fires_with_report(self, tmp_path: pytest.TempPathFactory) -> None:  # type: ignore[override]
        """The on_complete callback receives the final VerificationReport."""
        from odk.core.verifier import Verifier

        global_dir = tmp_path / "global"  # type: ignore[operator]
        project_dir = tmp_path / "project"  # type: ignore[operator]
        global_dir.mkdir(parents=True, exist_ok=True)
        project_dir.mkdir(parents=True, exist_ok=True)

        plugin_dir = global_dir / "ok"
        plugin_dir.mkdir()

        manifest = {
            "name": "ok",
            "description": "ok",
            "trigger": "manual:run",
            "parallel": True,
            "timeout": 10,
            "requires": [],
        }
        (plugin_dir / "manifest.yaml").write_text(yaml.dump(manifest))
        (plugin_dir / "check.py").write_text(
            'import json,sys;json.dump({"name":"ok","passed":True,"output":"ok","duration_seconds":0.0},sys.stdout)'
        )

        v = Verifier(
            project_root=tmp_path,  # type: ignore[arg-type]
            global_verifications=global_dir,
            project_verifications=project_dir,
        )

        received: list[VerificationReport] = []
        report = asyncio.run(
            v.run_all(
                context={"project_root": str(tmp_path)},
                on_complete=lambda r: received.append(r),
            )
        )
        assert len(received) == 1
        assert received[0] is report
        assert report.all_passed is True


# ---------------------------------------------------------------------------
# CLI --pr flag
# ---------------------------------------------------------------------------


class TestCLIPrFlag:
    def test_pr_flag_triggers_comment(self) -> None:
        """When --pr is provided, post_verification_results is called."""
        from typer.testing import CliRunner

        from odk.cli.verify_cmd import verify_app

        runner = CliRunner()

        with (
            patch("odk.cli.verify_cmd._make_verifier") as mock_mk,
            patch("odk.core.pr_commenter.PRCommenter.post_verification_results") as mock_post,
        ):
            fake_report = _sample_report(all_passed=True)
            mock_verifier = MagicMock()
            mock_verifier._root.resolve.return_value = "/fake"
            mock_mk.return_value = mock_verifier

            with patch("asyncio.run", return_value=fake_report):
                runner.invoke(
                    verify_app,
                    ["run", "--pr", "https://github.com/org/repo/pull/1"],
                )

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == "https://github.com/org/repo/pull/1"

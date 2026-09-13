"""Tests for the core task/PR lookup helpers (list_prs, find_task_pr)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from ydk.core.task_pr_lookup import find_task_pr, list_prs


class TestListPrs:
    def test_returns_empty_list_on_nonzero_returncode(self) -> None:
        fake_result = MagicMock(returncode=1, stdout="", stderr="gh: command not found")
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result):
            prs = list_prs()
        assert prs == []

    def test_returns_empty_list_on_malformed_json(self) -> None:
        fake_result = MagicMock(returncode=0, stdout="not json")
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result):
            prs = list_prs()
        assert prs == []

    def test_returns_empty_list_on_empty_stdout(self) -> None:
        fake_result = MagicMock(returncode=0, stdout="")
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result):
            prs = list_prs()
        assert prs == []

    def test_returns_parsed_list_on_success(self) -> None:
        data = [{"number": 1, "headRefName": "task/T-001"}]
        fake_result = MagicMock(returncode=0, stdout=json.dumps(data))
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result):
            prs = list_prs()
        assert prs == data

    def test_includes_limit_flag_in_gh_command(self) -> None:
        fake_result = MagicMock(returncode=0, stdout="[]")
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result) as mock_run:
            list_prs()
        cmd = mock_run.call_args[0][0]
        assert "--limit" in cmd
        assert "500" in cmd

    def test_returns_empty_list_when_gh_binary_missing_mid_call(self) -> None:
        """TOCTOU: gh disappears between an upstream `shutil.which("gh")` guard
        and this call (or list_prs() is invoked with no upstream guard at all).
        subprocess.run raises FileNotFoundError in that case; must degrade to []
        rather than propagate, matching doctor.py's graceful-degradation convention.
        """
        with patch("ydk.core.task_pr_lookup.subprocess.run", side_effect=FileNotFoundError("gh not found")):
            prs = list_prs()
        assert prs == []


class TestFindTaskPr:
    def test_returns_none_when_pr_list_empty(self) -> None:
        fake_result = MagicMock(returncode=0, stdout="[]")
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result):
            pr = find_task_pr("T-001")
        assert pr is None

    def test_returns_none_when_gh_call_fails(self) -> None:
        fake_result = MagicMock(returncode=1, stdout="", stderr="gh: command not found")
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result):
            pr = find_task_pr("T-001")
        assert pr is None

    def test_returns_none_on_malformed_json(self) -> None:
        fake_result = MagicMock(returncode=0, stdout="not json")
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result):
            pr = find_task_pr("T-001")
        assert pr is None

    def test_includes_limit_flag_in_gh_command(self) -> None:
        fake_result = MagicMock(returncode=0, stdout="[]")
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result) as mock_run:
            find_task_pr("T-001")
        cmd = mock_run.call_args[0][0]
        assert "--limit" in cmd

    def test_matches_exact_branch_name(self) -> None:
        prs = [
            {
                "number": 42,
                "url": "https://example.com/42",
                "state": "OPEN",
                "headRefName": "task/T-001",
                "mergedAt": None,
                "createdAt": "2026-01-01T00:00:00Z",
            }
        ]
        fake_result = MagicMock(returncode=0, stdout=json.dumps(prs))
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result):
            pr = find_task_pr("T-001")
        assert pr is not None
        assert pr["number"] == 42

    def test_matches_slugged_branch_name(self) -> None:
        prs = [
            {
                "number": 43,
                "url": "https://example.com/43",
                "state": "MERGED",
                "headRefName": "task/T-001-fix-thing",
                "mergedAt": "2026-01-02T00:00:00Z",
                "createdAt": "2026-01-01T00:00:00Z",
            }
        ]
        fake_result = MagicMock(returncode=0, stdout=json.dumps(prs))
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result):
            pr = find_task_pr("T-001")
        assert pr is not None
        assert pr["number"] == 43

    def test_matches_exact_quickdev_branch_name(self) -> None:
        prs = [
            {
                "number": 51,
                "url": "https://example.com/51",
                "state": "OPEN",
                "headRefName": "quickdev/QD-7583d5",
                "mergedAt": None,
                "createdAt": "2026-01-01T00:00:00Z",
            }
        ]
        fake_result = MagicMock(returncode=0, stdout=json.dumps(prs))
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result):
            pr = find_task_pr("QD-7583d5")
        assert pr is not None
        assert pr["number"] == 51

    def test_matches_slugged_quickdev_branch_name(self) -> None:
        prs = [
            {
                "number": 50,
                "url": "https://example.com/50",
                "state": "OPEN",
                "headRefName": "quickdev/QD-7583d5-fix-thing",
                "mergedAt": None,
                "createdAt": "2026-01-01T00:00:00Z",
            }
        ]
        fake_result = MagicMock(returncode=0, stdout=json.dumps(prs))
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result):
            pr = find_task_pr("QD-7583d5")
        assert pr is not None
        assert pr["number"] == 50

    def test_matches_branch_with_different_leading_type_segment(self) -> None:
        """Branches from other schemes (e.g. quickdev's chore/qd-... or docs/qd-...)
        should match on the last path segment, case-insensitively, independent
        of the leading type prefix.
        """
        prs = [
            {
                "number": 50,
                "url": "https://example.com/50",
                "state": "OPEN",
                "headRefName": "chore/qd-7583d5-fix-thing",
                "mergedAt": None,
                "createdAt": "2026-01-01T00:00:00Z",
            }
        ]
        fake_result = MagicMock(returncode=0, stdout=json.dumps(prs))
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result):
            pr = find_task_pr("QD-7583d5")
        assert pr is not None
        assert pr["number"] == 50

    def test_matches_task_prefix_case_insensitively(self) -> None:
        prs = [
            {
                "number": 60,
                "url": "https://example.com/60",
                "state": "OPEN",
                "headRefName": "task/t-a1b2c3d4-fix-thing",
                "mergedAt": None,
                "createdAt": "2026-01-01T00:00:00Z",
            }
        ]
        fake_result = MagicMock(returncode=0, stdout=json.dumps(prs))
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result):
            pr = find_task_pr("T-A1B2C3D4")
        assert pr is not None
        assert pr["number"] == 60

    def test_does_not_match_prefix_collision(self) -> None:
        """Querying T-001 must not match a PR on branch task/T-0010."""
        prs = [
            {
                "number": 44,
                "url": "https://example.com/44",
                "state": "OPEN",
                "headRefName": "task/T-0010",
                "mergedAt": None,
                "createdAt": "2026-01-01T00:00:00Z",
            }
        ]
        fake_result = MagicMock(returncode=0, stdout=json.dumps(prs))
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result):
            pr = find_task_pr("T-001")
        assert pr is None

    def test_does_not_match_quickdev_prefix_collision(self) -> None:
        """Querying QD-001 must not match a PR on branch quickdev/QD-0010."""
        prs = [
            {
                "number": 45,
                "url": "https://example.com/45",
                "state": "OPEN",
                "headRefName": "quickdev/QD-0010",
                "mergedAt": None,
                "createdAt": "2026-01-01T00:00:00Z",
            }
        ]
        fake_result = MagicMock(returncode=0, stdout=json.dumps(prs))
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result):
            pr = find_task_pr("QD-001")
        assert pr is None

    def test_returns_most_recently_created_when_multiple_matches(self) -> None:
        prs = [
            {
                "number": 1,
                "url": "https://example.com/1",
                "state": "CLOSED",
                "headRefName": "task/T-001",
                "mergedAt": None,
                "createdAt": "2026-01-01T00:00:00Z",
            },
            {
                "number": 2,
                "url": "https://example.com/2",
                "state": "OPEN",
                "headRefName": "task/T-001-retry",
                "mergedAt": None,
                "createdAt": "2026-02-01T00:00:00Z",
            },
        ]
        fake_result = MagicMock(returncode=0, stdout=json.dumps(prs))
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result):
            pr = find_task_pr("T-001")
        assert pr is not None
        assert pr["number"] == 2

    def test_ignores_unrelated_branches(self) -> None:
        prs = [
            {
                "number": 10,
                "url": "https://example.com/10",
                "state": "OPEN",
                "headRefName": "task/T-999",
                "mergedAt": None,
                "createdAt": "2026-01-01T00:00:00Z",
            },
            {
                "number": 11,
                "url": "https://example.com/11",
                "state": "OPEN",
                "headRefName": "main",
                "mergedAt": None,
                "createdAt": "2026-01-01T00:00:00Z",
            },
            {
                "number": 12,
                "url": "https://example.com/12",
                "state": "MERGED",
                "headRefName": "task/T-001",
                "mergedAt": "2026-01-02T00:00:00Z",
                "createdAt": "2026-01-01T12:00:00Z",
            },
        ]
        fake_result = MagicMock(returncode=0, stdout=json.dumps(prs))
        with patch("ydk.core.task_pr_lookup.subprocess.run", return_value=fake_result):
            pr = find_task_pr("T-001")
        assert pr is not None
        assert pr["number"] == 12

    def test_uses_passed_in_prs_and_does_not_call_subprocess(self) -> None:
        prs = [
            {
                "number": 42,
                "url": "https://example.com/42",
                "state": "OPEN",
                "headRefName": "task/T-001",
                "mergedAt": None,
                "createdAt": "2026-01-01T00:00:00Z",
            }
        ]
        with patch("ydk.core.task_pr_lookup.subprocess.run") as mock_run:
            pr = find_task_pr("T-001", prs=prs)
        mock_run.assert_not_called()
        assert pr is not None
        assert pr["number"] == 42

    def test_uses_passed_in_prs_returns_none_when_no_match(self) -> None:
        with patch("ydk.core.task_pr_lookup.subprocess.run") as mock_run:
            pr = find_task_pr("T-001", prs=[])
        mock_run.assert_not_called()
        assert pr is None

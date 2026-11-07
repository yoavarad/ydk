"""Tests for GitHubRemoteService — all mocked (no real GitHub calls)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from ydk.services.remote import GitHubRemoteService


class TestCreateIssue:
    def test_constructs_correct_command(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=0, stdout="https://github.com/org/repo/issues/42\n")
        with patch("subprocess.run", return_value=fake) as mock_run:
            url = svc.create_issue("Bug title", "Bug body", ["bug", "p1"])
        assert url == "https://github.com/org/repo/issues/42"
        cmd = mock_run.call_args[0][0]
        assert "gh" in cmd
        assert "issue" in cmd
        assert "create" in cmd
        assert "--title" in cmd
        assert "Bug title" in cmd
        assert "--label" in cmd

    def test_with_milestone(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=0, stdout="https://github.com/org/repo/issues/43\n")
        with patch("subprocess.run", return_value=fake) as mock_run:
            svc.create_issue("Title", "Body", ["feat"], milestone="v1.0")
        cmd = mock_run.call_args[0][0]
        assert "--milestone" in cmd
        assert "v1.0" in cmd

    def test_raises_on_failure(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=1, stdout="", stderr="auth error")
        with patch("subprocess.run", return_value=fake), pytest.raises(RuntimeError):
            svc.create_issue("Title", "Body", ["bug"])


class TestListIssues:
    def test_parses_json_output(self) -> None:
        svc = GitHubRemoteService()
        issues = [
            {"number": 1, "title": "First", "state": "OPEN", "labels": [{"name": "bug"}], "body": "desc"},
            {"number": 2, "title": "Second", "state": "OPEN", "labels": [], "body": ""},
        ]
        fake = MagicMock(returncode=0, stdout=json.dumps(issues))
        with patch("subprocess.run", return_value=fake):
            result = svc.list_issues()
        assert len(result) == 2
        assert result[0]["number"] == 1

    def test_with_filters(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=0, stdout="[]")
        with patch("subprocess.run", return_value=fake) as mock_run:
            svc.list_issues(milestone="v1.0", labels=["bug"], state="closed")
        cmd = mock_run.call_args[0][0]
        assert "--milestone" in cmd
        assert "--label" in cmd
        assert "--state" in cmd
        assert "closed" in cmd

    def test_returns_empty_on_failure(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=1, stdout="", stderr="error")
        with patch("subprocess.run", return_value=fake):
            result = svc.list_issues()
        assert result == []


class TestAddLabel:
    def test_calls_correct_command(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=0, stdout="")
        with patch("subprocess.run", return_value=fake) as mock_run:
            svc.add_label(42, "priority/high")
        cmd = mock_run.call_args[0][0]
        assert "gh" in cmd
        assert "issue" in cmd
        assert "edit" in cmd
        assert "42" in [str(c) for c in cmd]
        assert "--add-label" in cmd
        assert "priority/high" in cmd

    def test_raises_on_failure(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=1, stdout="", stderr="not found")
        with patch("subprocess.run", return_value=fake), pytest.raises(RuntimeError):
            svc.add_label(999, "bug")


class TestAddComment:
    def test_calls_correct_command(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=0, stdout="")
        with patch("subprocess.run", return_value=fake) as mock_run:
            svc.add_comment(42, "LGTM!")
        cmd = mock_run.call_args[0][0]
        assert "gh" in cmd
        assert "issue" in cmd
        assert "comment" in cmd
        assert "42" in [str(c) for c in cmd]
        assert "--body" in cmd
        assert "LGTM!" in cmd

    def test_raises_on_failure(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=1, stdout="", stderr="error")
        with patch("subprocess.run", return_value=fake), pytest.raises(RuntimeError):
            svc.add_comment(42, "comment")


class TestListIssuesLimits:
    def test_github_passes_explicit_limit(self) -> None:
        svc = GitHubRemoteService()
        fake = MagicMock(returncode=0, stdout="[]")
        with patch("subprocess.run", return_value=fake) as mock_run:
            svc.list_issues()
        cmd = mock_run.call_args[0][0]
        assert int(cmd[cmd.index("--limit") + 1]) >= 1000

    def test_gitlab_follows_pages(self) -> None:
        from ydk.services.remote import GitLabRemoteService

        full = MagicMock(returncode=0, stdout=json.dumps([{"iid": n} for n in range(100)]))
        short = MagicMock(returncode=0, stdout=json.dumps([{"iid": n} for n in range(100, 105)]))
        with patch("subprocess.run", side_effect=[full, short]) as mock_run:
            result = GitLabRemoteService().list_issues()
        assert len(result) == 105
        second_cmd = mock_run.call_args_list[1][0][0]
        assert second_cmd[second_cmd.index("--page") + 1] == "2"

    @pytest.mark.parametrize(("state", "flags"), [("open", []), ("closed", ["--closed"]), ("all", ["--all"])])
    def test_gitlab_state_flags(self, state: str, flags: list[str]) -> None:
        from ydk.services.remote import GitLabRemoteService

        fake = MagicMock(returncode=0, stdout="[]")
        with patch("subprocess.run", return_value=fake) as mock_run:
            GitLabRemoteService().list_issues(state=state)
        cmd = mock_run.call_args[0][0]
        assert "--state" not in cmd
        assert [f for f in ("--closed", "--all") if f in cmd] == flags

    def test_gitlab_failure_raises(self) -> None:
        from ydk.services.remote import GitLabRemoteService

        fake = MagicMock(returncode=1, stdout="", stderr="unknown flag")
        with patch("subprocess.run", return_value=fake), pytest.raises(RuntimeError, match="unknown flag"):
            GitLabRemoteService().list_issues()


MR_URL = "https://gitlab.com/group/proj/-/merge_requests/7"
PROJECT_URL = "https://gitlab.com/group/proj"


class TestGitLabCreateMergeRequest:
    def test_builds_glab_mr_create_and_returns_url(self) -> None:
        from ydk.services.remote import GitLabRemoteService

        stdout = f"\nCreating merge request for task/1 into main in group/proj\n\n!7 Task 1: x (task/1)\n {MR_URL}\n\n"
        fake = MagicMock(returncode=0, stdout=stdout, stderr="")
        with patch("ydk.services.remote.subprocess.run", return_value=fake) as mock_run:
            url = GitLabRemoteService().create_merge_request("Task 1: x", "/tmp/body.md", "task/1", "main", cwd="/wt")
        assert url == MR_URL
        cmd = mock_run.call_args[0][0]
        assert cmd == [
            "glab",
            "mr",
            "create",
            "--title",
            "Task 1: x",
            "--description-file",
            "/tmp/body.md",
            "--source-branch",
            "task/1",
            "--target-branch",
            "main",
            "--yes",
        ]
        assert mock_run.call_args.kwargs["cwd"] == "/wt"
        assert mock_run.call_args.kwargs["encoding"] == "utf-8"

    def test_raises_with_stderr_on_failure(self) -> None:
        from ydk.services.remote import GitLabRemoteService

        fake = MagicMock(returncode=1, stdout="", stderr="403 Forbidden")
        with (
            patch("ydk.services.remote.subprocess.run", return_value=fake),
            pytest.raises(RuntimeError, match="403 Forbidden"),
        ):
            GitLabRemoteService().create_merge_request("t", "/b.md", "task/1", "main")

    def test_raises_when_no_url_printed(self) -> None:
        from ydk.services.remote import GitLabRemoteService

        fake = MagicMock(returncode=0, stdout="done\n", stderr="")
        with (
            patch("ydk.services.remote.subprocess.run", return_value=fake),
            pytest.raises(RuntimeError, match="no MR URL"),
        ):
            GitLabRemoteService().create_merge_request("t", "/b.md", "task/1", "main")


class TestGitLabFindMergeRequest:
    def test_returns_iid_of_first_match(self) -> None:
        from ydk.services.remote import GitLabRemoteService

        payload = json.dumps([{"iid": 7, "web_url": MR_URL}, {"iid": 3}])
        fake = MagicMock(returncode=0, stdout=payload, stderr="")
        with patch("ydk.services.remote.subprocess.run", return_value=fake) as mock_run:
            iid = GitLabRemoteService().find_merge_request_iid("task/1")
        assert iid == "7"
        assert mock_run.call_args[0][0] == [
            "glab",
            "mr",
            "list",
            "--source-branch",
            "task/1",
            "--all",
            "--output",
            "json",
        ]

    @pytest.mark.parametrize(
        "fake",
        [
            MagicMock(returncode=1, stdout="", stderr="boom"),
            MagicMock(returncode=0, stdout="[]", stderr=""),
            MagicMock(returncode=0, stdout="not json", stderr=""),
            MagicMock(returncode=0, stdout='{"error": {"message": "x"}}', stderr=""),
        ],
    )
    def test_returns_none_when_missing_or_failed(self, fake: MagicMock) -> None:
        from ydk.services.remote import GitLabRemoteService

        with patch("ydk.services.remote.subprocess.run", return_value=fake):
            assert GitLabRemoteService().find_merge_request_iid("task/1") is None


class TestGitLabMergeRequestState:
    @pytest.mark.parametrize(
        ("glab_state", "expected"),
        [("merged", "MERGED"), ("opened", "OPEN"), ("closed", "CLOSED"), ("locked", "LOCKED")],
    )
    def test_maps_state_to_github_values(self, glab_state: str, expected: str) -> None:
        from ydk.services.remote import GitLabRemoteService

        fake = MagicMock(returncode=0, stdout=json.dumps({"iid": 7, "state": glab_state}), stderr="")
        with patch("ydk.services.remote.subprocess.run", return_value=fake) as mock_run:
            assert GitLabRemoteService().merge_request_state(MR_URL) == expected
        assert mock_run.call_args[0][0] == ["glab", "mr", "view", "7", "--repo", PROJECT_URL, "--output", "json"]

    @pytest.mark.parametrize(
        "fake",
        [
            MagicMock(returncode=1, stdout="", stderr="404"),
            MagicMock(returncode=0, stdout="not json", stderr=""),
            MagicMock(returncode=0, stdout="[]", stderr=""),
        ],
    )
    def test_returns_none_on_failure(self, fake: MagicMock) -> None:
        from ydk.services.remote import GitLabRemoteService

        with patch("ydk.services.remote.subprocess.run", return_value=fake):
            assert GitLabRemoteService().merge_request_state(MR_URL) is None

    def test_returns_none_for_non_mr_url_without_calling_glab(self) -> None:
        from ydk.services.remote import GitLabRemoteService

        with patch("ydk.services.remote.subprocess.run") as mock_run:
            assert GitLabRemoteService().merge_request_state("local://T-1/pr-pending") is None
        mock_run.assert_not_called()


class TestGitLabMergeRequestNote:
    def test_builds_glab_mr_note_create(self) -> None:
        from ydk.services.remote import GitLabRemoteService

        fake = MagicMock(returncode=0, stdout="", stderr="")
        with patch("ydk.services.remote.subprocess.run", return_value=fake) as mock_run:
            GitLabRemoteService().add_merge_request_note(MR_URL, "hello")
        assert mock_run.call_args[0][0] == [
            "glab",
            "mr",
            "note",
            "create",
            "7",
            "--repo",
            PROJECT_URL,
            "--message",
            "hello",
        ]

    def test_raises_on_failure(self) -> None:
        from ydk.services.remote import GitLabRemoteService

        fake = MagicMock(returncode=1, stdout="", stderr="denied")
        with (
            patch("ydk.services.remote.subprocess.run", return_value=fake),
            pytest.raises(RuntimeError, match="denied"),
        ):
            GitLabRemoteService().add_merge_request_note(MR_URL, "hello")

    def test_raises_for_non_mr_url(self) -> None:
        from ydk.services.remote import GitLabRemoteService

        with pytest.raises(ValueError, match="merge request URL"):
            GitLabRemoteService().add_merge_request_note("https://github.com/o/r/pull/1", "hello")


class TestGitLabMrUrlVariants:
    @pytest.mark.parametrize(
        "url",
        [
            f"{MR_URL}/",
            f"{MR_URL}/diffs",
            f"{MR_URL}#note_1",
            f"{MR_URL}?tab=commits",
        ],
    )
    def test_state_accepts_url_suffixes(self, url: str) -> None:
        from ydk.services.remote import GitLabRemoteService

        fake = MagicMock(returncode=0, stdout=json.dumps({"state": "merged"}), stderr="")
        with patch("ydk.services.remote.subprocess.run", return_value=fake) as mock_run:
            assert GitLabRemoteService().merge_request_state(url) == "MERGED"
        assert mock_run.call_args[0][0][3:6] == ["7", "--repo", PROJECT_URL]

    def test_subgroup_and_self_hosted_port(self) -> None:
        from ydk.services.remote import GitLabRemoteService

        url = "https://git.example.com:8443/a/b/c/-/merge_requests/12"
        fake = MagicMock(returncode=0, stdout=json.dumps({"state": "opened"}), stderr="")
        with patch("ydk.services.remote.subprocess.run", return_value=fake) as mock_run:
            assert GitLabRemoteService().merge_request_state(url) == "OPEN"
        assert mock_run.call_args[0][0][3:6] == ["12", "--repo", "https://git.example.com:8443/a/b/c"]


class TestIsGitLabRemote:
    def test_true_for_gitlab(self, tmp_path) -> None:
        from ydk.services.remote import is_gitlab_remote

        cfg = tmp_path / "config.yaml"
        cfg.write_text("project:\n  name: p\n  remote: gitlab\n", encoding="utf-8")
        assert is_gitlab_remote(cfg) is True

    def test_false_for_github_missing_or_invalid(self, tmp_path) -> None:
        from ydk.services.remote import is_gitlab_remote

        gh = tmp_path / "gh.yaml"
        gh.write_text("project:\n  name: p\n  remote: github\n", encoding="utf-8")
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("project: [unclosed\n", encoding="utf-8")
        invalid = tmp_path / "invalid.yaml"
        invalid.write_text("project:\n  remote: gitlab\n", encoding="utf-8")  # missing required name
        assert is_gitlab_remote(gh) is False
        assert is_gitlab_remote(tmp_path / "missing.yaml") is False
        assert is_gitlab_remote(bad_yaml) is False
        assert is_gitlab_remote(invalid) is False

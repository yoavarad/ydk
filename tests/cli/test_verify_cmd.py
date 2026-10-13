"""Tests for ydk verify CLI commands."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

from typer.testing import CliRunner

from ydk.cli import app
from ydk.core.verifier import VerificationPlugin, Verifier
from ydk.models.verification import CheckResult, VerificationReport

runner = CliRunner()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _ok_check(name: str = "lint") -> CheckResult:
    return CheckResult(name=name, passed=True, output="ok", duration_seconds=0.1)


def _fail_check(name: str = "lint") -> CheckResult:
    return CheckResult(name=name, passed=False, output="error found", duration_seconds=0.2)


def _ok_report() -> VerificationReport:
    return VerificationReport(
        timestamp="2026-04-26T00:00:00Z",
        checks=[_ok_check("lint"), _ok_check("types")],
        all_passed=True,
        total_duration_seconds=0.5,
    )


def _fail_report() -> VerificationReport:
    return VerificationReport(
        timestamp="2026-04-26T00:00:00Z",
        checks=[_ok_check("lint"), _fail_check("types")],
        all_passed=False,
        total_duration_seconds=0.5,
    )


def _sample_plugin(name: str = "test-plugin") -> VerificationPlugin:
    return VerificationPlugin(
        name=name,
        description="A test plugin",
        trigger="git:pre-commit",
        parallel=True,
        timeout=30,
        requires=[],
        check_script=Path("/fake/check.py"),
    )


class TestVerifyRun:
    def test_exits_zero_when_all_pass(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.run_all",
            AsyncMock(return_value=_ok_report()),
        )
        result = runner.invoke(app, ["verify", "run"])
        assert result.exit_code == 0
        assert "ALL PASSED" in result.output

    def test_exits_one_when_any_check_fails(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.run_all",
            AsyncMock(return_value=_fail_report()),
        )
        result = runner.invoke(app, ["verify", "run"])
        assert result.exit_code == 1
        assert "FAILED" in result.output

    def test_save_proof_writes_file(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.run_all",
            AsyncMock(return_value=_ok_report()),
        )
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.save_proof",
            lambda self, report, task_id=None: tmp_path / "verification.json",
        )
        result = runner.invoke(app, ["verify", "run", "--save-proof"])
        assert result.exit_code == 0
        assert "Proof saved" in result.output

    def test_filter_by_name(self, monkeypatch) -> None:
        plugin = _sample_plugin("my-check")
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.discover_plugins",
            lambda self: [plugin],
        )
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.filter_by_name",
            lambda self, plugins, name: [p for p in plugins if p.name == name],
        )
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.run_layer",
            AsyncMock(return_value=[_ok_check("my-check")]),
        )
        result = runner.invoke(app, ["verify", "run", "--name", "my-check"])
        assert result.exit_code == 0

    def test_name_not_found_exits_one(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.discover_plugins",
            lambda self: [],
        )
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.filter_by_name",
            lambda self, plugins, name: [],
        )
        result = runner.invoke(app, ["verify", "run", "--name", "nope"])
        assert result.exit_code == 1


class TestVerifyRetry:
    def test_retry_passes_on_first_try(self, monkeypatch) -> None:
        """--retry with an immediately passing verifier exits 0."""
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.run_all",
            AsyncMock(return_value=_ok_report()),
        )
        result = runner.invoke(app, ["verify", "run", "--retry", "3"])
        assert result.exit_code == 0
        assert "ALL PASSED" in result.output
        assert "1 attempt(s)" in result.output

    def test_retry_fails_then_passes(self, monkeypatch) -> None:
        """--retry with a verifier that fails once then passes."""
        mock = AsyncMock(side_effect=[_fail_report(), _ok_report()])
        monkeypatch.setattr("ydk.cli.verify_cmd.Verifier.run_all", mock)
        result = runner.invoke(app, ["verify", "run", "--retry", "3"])
        assert result.exit_code == 0
        assert "ALL PASSED" in result.output
        assert "2 attempt(s)" in result.output
        assert "Structured errors" in result.output

    def test_retry_max_reached(self, monkeypatch) -> None:
        """--retry exits 1 when max retries exhausted."""
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.run_all",
            AsyncMock(return_value=_fail_report()),
        )
        result = runner.invoke(app, ["verify", "run", "--retry", "2"])
        assert result.exit_code == 1
        assert "FAILED" in result.output
        assert "max retries reached" in result.output

    def test_repair_is_alias_for_retry_3(self, monkeypatch) -> None:
        """--repair is shorthand for --retry 3."""
        call_count = {"n": 0}
        original_fail = _fail_report()

        async def counting_run_all(*args: object, **kwargs: object) -> VerificationReport:
            call_count["n"] += 1
            return original_fail

        monkeypatch.setattr("ydk.cli.verify_cmd.Verifier.run_all", counting_run_all)
        result = runner.invoke(app, ["verify", "run", "--repair"])
        assert result.exit_code == 1
        assert call_count["n"] == 3  # --repair = --retry 3

    def test_retry_displays_structured_json(self, monkeypatch) -> None:
        """Structured error JSON is displayed between attempts."""
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.run_all",
            AsyncMock(side_effect=[_fail_report(), _ok_report()]),
        )
        result = runner.invoke(app, ["verify", "run", "--retry", "3"])
        assert result.exit_code == 0
        assert "failed_checks" in result.output
        assert '"name": "types"' in result.output


class TestVerifyRunChangedFiles:
    @staticmethod
    def _develop_repo(tmp_path: Path, monkeypatch) -> None:
        """Repo whose only branch is ``develop``; a task branch adds b.txt."""
        _git(tmp_path, "init", "-q", "-b", "develop")
        (tmp_path / "a.txt").write_text("a\n")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "init")
        _git(tmp_path, "checkout", "-q", "-b", "task/9-x")
        (tmp_path / "b.txt").write_text("b\n")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "add b")
        _git(tmp_path, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop")
        monkeypatch.chdir(tmp_path)

    def test_pre_push_trigger_diffs_against_default_branch_not_main(self, tmp_path: Path, monkeypatch) -> None:
        self._develop_repo(tmp_path, monkeypatch)
        mock_run_all = AsyncMock(return_value=_ok_report())
        monkeypatch.setattr("ydk.cli.verify_cmd.Verifier.run_all", mock_run_all)
        result = runner.invoke(app, ["verify", "run", "--trigger", "pre-push"])
        assert result.exit_code == 0
        assert mock_run_all.call_args.kwargs["context"]["changed_files"] == ["b.txt"]

    def test_pre_push_retry_path_diffs_against_default_branch(self, tmp_path: Path, monkeypatch) -> None:
        self._develop_repo(tmp_path, monkeypatch)
        mock_run_all = AsyncMock(return_value=_ok_report())
        monkeypatch.setattr("ydk.cli.verify_cmd.Verifier.run_all", mock_run_all)
        result = runner.invoke(app, ["verify", "run", "--trigger", "pre-push", "--retry", "3"])
        assert result.exit_code == 0
        assert mock_run_all.call_args.kwargs["context"]["changed_files"] == ["b.txt"]

    def test_pre_push_empty_changed_files_not_injected(self, monkeypatch) -> None:
        mock_run_all = AsyncMock(return_value=_ok_report())
        monkeypatch.setattr("ydk.cli.verify_cmd.Verifier.run_all", mock_run_all)
        monkeypatch.setattr(
            "ydk.services.git.LocalGitService.changed_files",
            lambda self, directory, base_ref=None, extension="": [],
        )
        result = runner.invoke(app, ["verify", "run", "--trigger", "pre-push"])
        assert result.exit_code == 0
        assert "changed_files" not in mock_run_all.call_args.kwargs["context"]

    def test_non_pre_push_trigger_does_not_inject_changed_files(self, monkeypatch) -> None:
        mock_run_all = AsyncMock(return_value=_ok_report())
        monkeypatch.setattr("ydk.cli.verify_cmd.Verifier.run_all", mock_run_all)
        result = runner.invoke(app, ["verify", "run", "--trigger", "pre-commit"])
        assert result.exit_code == 0
        assert "changed_files" not in mock_run_all.call_args.kwargs["context"]

    def test_default_manual_trigger_does_not_inject_changed_files(self, monkeypatch) -> None:
        mock_run_all = AsyncMock(return_value=_ok_report())
        monkeypatch.setattr("ydk.cli.verify_cmd.Verifier.run_all", mock_run_all)
        result = runner.invoke(app, ["verify", "run"])
        assert result.exit_code == 0
        assert "changed_files" not in mock_run_all.call_args.kwargs["context"]


class TestVerifyList:
    def test_shows_plugins(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.discover_plugins",
            lambda self: [_sample_plugin("lint-ruff"), _sample_plugin("tests-pytest")],
        )
        result = runner.invoke(app, ["verify", "list"])
        assert result.exit_code == 0
        assert "lint-ruff" in result.output
        assert "tests-pytest" in result.output

    def test_empty_plugins(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.discover_plugins",
            lambda self: [],
        )
        result = runner.invoke(app, ["verify", "list"])
        assert result.exit_code == 0
        assert "No verification plugins found" in result.output


class TestVerifyCreate:
    def test_creates_plugin_directory(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["verify", "create", "my-check", "--trigger", "git:pre-push"])
        assert result.exit_code == 0
        assert "Created plugin" in result.output
        plugin_dir = tmp_path / ".ydk" / "verifications" / "my-check"
        assert (plugin_dir / "manifest.yaml").exists()
        assert (plugin_dir / "check.py").exists()

    def test_command_option_writes_command_only_manifest(self, monkeypatch, tmp_path: Path) -> None:
        import yaml

        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["verify", "create", "foo", "--command", "make test"])
        assert result.exit_code == 0
        plugin_dir = tmp_path / ".ydk" / "verifications" / "foo"
        data = yaml.safe_load((plugin_dir / "manifest.yaml").read_text(encoding="utf-8"))
        assert data["command"] == "make test"
        assert not (plugin_dir / "check.py").exists()


class TestVerifySkipPlugin:
    def test_skip_plugin_repeatable_excludes_plugins(self, monkeypatch) -> None:
        captured: dict[str, object] = {}
        real_init = Verifier.__init__

        def spy_init(self: Verifier, *args: object, **kwargs: object) -> None:
            captured["skip"] = kwargs.get("skip_plugins")
            real_init(self, *args, **kwargs)

        monkeypatch.setattr("ydk.cli.verify_cmd.Verifier.__init__", spy_init)
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.run_all",
            AsyncMock(return_value=_ok_report()),
        )
        result = runner.invoke(app, ["verify", "run", "--skip-plugin", "a", "--skip-plugin", "b"])
        assert result.exit_code == 0
        assert captured["skip"] == ["a", "b"]

    @staticmethod
    def _patch_verifier(monkeypatch, tmp_path: Path, skip: list[str]) -> None:
        proj = tmp_path / "proj"
        for name, trig in (("ai-code-review", "git:pre-push"), ("commit-only", "git:pre-commit")):
            d = proj / name
            d.mkdir(parents=True)
            (d / "manifest.yaml").write_text(f"name: {name}\ndescription: x\ntrigger: {trig}\n")
            out = {"name": name, "passed": True, "output": "ok", "duration_seconds": 0.0}
            (d / "check.py").write_text(f"import json, sys\njson.dump({out!r}, sys.stdout)\n")
        monkeypatch.setattr(
            "ydk.cli.verify_cmd._make_verifier",
            lambda **_kw: Verifier(
                project_root=tmp_path,
                global_verifications=tmp_path / "none",
                project_verifications=proj,
                use_cache=False,
                skip_plugins=skip,
            ),
        )

    def test_triggered_skipped_plugin_reported_as_skipped(self, monkeypatch, tmp_path: Path) -> None:
        self._patch_verifier(monkeypatch, tmp_path, ["ai-code-review"])
        result = runner.invoke(app, ["verify", "run", "--trigger", "git:pre-push", "--skip-plugin", "ai-code-review"])
        assert result.exit_code == 0
        assert "ai-code-review (skipped)" in result.output

    def test_skip_of_non_triggered_plugin_not_reported(self, monkeypatch, tmp_path: Path) -> None:
        self._patch_verifier(monkeypatch, tmp_path, ["commit-only"])
        result = runner.invoke(app, ["verify", "run", "--trigger", "git:pre-push", "--skip-plugin", "commit-only"])
        assert result.exit_code == 0
        assert "skipped" not in result.output
        assert "ai-code-review" in result.output


# --- verify pr-body ---

_GOOD_PR_BODY = "## Summary\n\nDid it.\n\n## Test Plan\n\n```console\n$ pytest\nok\n```\n"


def test_pr_body_passes_for_good_body(tmp_path: Path) -> None:
    body = tmp_path / "body.md"
    body.write_text(_GOOD_PR_BODY, encoding="utf-8")
    result = runner.invoke(app, ["verify", "pr-body", "--body-file", str(body)])
    assert result.exit_code == 0, result.output


def test_pr_body_fails_without_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    body = tmp_path / "body.md"
    body.write_text("## Test Plan\n\n```console\nok\n```\n", encoding="utf-8")
    result = runner.invoke(app, ["verify", "pr-body", "--body-file", str(body)])
    assert result.exit_code == 1
    assert "summary" in result.output.lower()
    assert "::error::" not in result.output


def test_pr_body_emits_error_annotations_in_github_actions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    body = tmp_path / "body.md"
    body.write_text("nothing", encoding="utf-8")
    result = runner.invoke(app, ["verify", "pr-body", "--body-file", str(body)])
    assert result.exit_code == 1
    assert "::error::PR body must contain a ## Summary section" in result.output


def test_pr_body_annotates_fail_on_first_output_line(tmp_path: Path, monkeypatch) -> None:
    from ydk.core import pr_body_check
    from ydk.models.verification import CheckResult

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    fake = CheckResult(
        name="pr-body-validation", passed=False, output="FAIL: first line problem\nFAIL: second", duration_seconds=0.0
    )
    monkeypatch.setattr(pr_body_check, "run_pr_body_validation", lambda *a, **k: fake)
    body = tmp_path / "body.md"
    body.write_text("x", encoding="utf-8")
    result = runner.invoke(app, ["verify", "pr-body", "--body-file", str(body)])
    assert result.exit_code == 1
    assert "::error::first line problem" in result.output
    assert "::error::second" in result.output


def test_pr_body_base_ref_feeds_changed_files(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t.t")
    git("config", "user.name", "t")
    (tmp_path / "a.txt").write_text("a")
    git("add", ".")
    git("commit", "-q", "-m", "init")
    git("checkout", "-q", "-b", "feat")
    (tmp_path / "App.tsx").write_text("x")
    git("add", ".")
    git("commit", "-q", "-m", "ui")

    body = tmp_path.parent / "body-ref.md"
    body.write_text(_GOOD_PR_BODY, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["verify", "pr-body", "--body-file", str(body), "--base-ref", "main"])
    assert result.exit_code == 1
    assert "screenshot" in result.output.lower()


def test_pr_body_exits_1_when_plugin_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("ydk.core.pr_body_check.run_pr_body_validation", lambda *a, **k: None)
    body = tmp_path / "body.md"
    body.write_text(_GOOD_PR_BODY, encoding="utf-8")
    result = runner.invoke(app, ["verify", "pr-body", "--body-file", str(body)])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_pr_body_exits_1_on_invalid_base_ref(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    body = tmp_path / "body.md"
    body.write_text(_GOOD_PR_BODY, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["verify", "pr-body", "--body-file", str(body), "--base-ref", "nope"])
    assert result.exit_code == 1
    assert "base-ref" in result.output.lower()


class TestDotnetTargetContext:
    @staticmethod
    def _run_with_dump_plugin(monkeypatch, tmp_path: Path, config_yaml: str) -> dict:
        """Run `verify run` with a stub plugin that dumps the stdin context it receives."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".ydk").mkdir()
        (tmp_path / ".ydk" / "config.yaml").write_text(config_yaml)
        proj = tmp_path / "proj"
        d = proj / "dump-ctx"
        d.mkdir(parents=True)
        (d / "manifest.yaml").write_text("name: dump-ctx\ndescription: x\ntrigger: manual\n")
        dump = tmp_path / "ctx.json"
        (d / "check.py").write_text(
            "import json, sys\n"
            "ctx = sys.stdin.read()\n"
            f"open({str(dump)!r}, 'w').write(ctx)\n"
            "json.dump({'name': 'dump-ctx', 'passed': True, 'output': 'ok', 'duration_seconds': 0.0}, sys.stdout)\n"
        )
        monkeypatch.setattr(
            "ydk.cli.verify_cmd._make_verifier",
            lambda **_kw: Verifier(
                project_root=tmp_path,
                global_verifications=tmp_path / "none",
                project_verifications=proj,
                use_cache=False,
            ),
        )
        result = runner.invoke(app, ["verify", "run", "--trigger", "manual"])
        assert result.exit_code == 0, result.output
        return json.loads(dump.read_text())

    def test_dotnet_target_reaches_context_config(self, monkeypatch, tmp_path: Path) -> None:
        ctx = self._run_with_dump_plugin(
            monkeypatch,
            tmp_path,
            "project:\n  name: x\nverification:\n  dotnet:\n    target: src/App.sln\n",
        )
        assert ctx["config"]["dotnet"] == {"target": "src/App.sln"}

    def test_no_dotnet_key_when_unset(self, monkeypatch, tmp_path: Path) -> None:
        ctx = self._run_with_dump_plugin(monkeypatch, tmp_path, "project:\n  name: x\n")
        assert "dotnet" not in ctx["config"]

    def test_go_config_reaches_context_config(self, monkeypatch, tmp_path: Path) -> None:
        ctx = self._run_with_dump_plugin(
            monkeypatch,
            tmp_path,
            "project:\n  name: x\nverification:\n  go:\n"
            "    coverage_min: 80\n    coverage_packages: [internal/censor]\n",
        )
        assert ctx["config"]["go"] == {
            "coverage_min": 80.0,
            "coverage_packages": ["internal/censor"],
            "test_tags": [],
            "race": True,
        }

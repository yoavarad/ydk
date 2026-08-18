"""Tests for ydk verify CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from typer.testing import CliRunner

from ydk.cli import app
from ydk.core.verifier import VerificationPlugin
from ydk.models.verification import CheckResult, VerificationReport

runner = CliRunner()


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

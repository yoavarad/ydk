"""Tests for auto-fix capability in the verification system."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from ydk.core.verifier import Verifier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_plugin(
    plugin_dir: Path,
    name: str,
    trigger: str = "git:pre-commit",
    parallel: bool = True,
    timeout: int = 30,
    requires: list[str] | None = None,
    supports_auto_fix: bool = False,
    check_code: str | None = None,
) -> Path:
    """Create a minimal plugin folder with manifest.yaml + check.py."""
    folder = plugin_dir / name
    folder.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "name": name,
        "description": f"Test plugin: {name}",
        "trigger": trigger,
        "parallel": parallel,
        "timeout": timeout,
        "requires": requires or [],
        "supports_auto_fix": supports_auto_fix,
    }
    (folder / "manifest.yaml").write_text(yaml.dump(manifest, default_flow_style=False))

    if check_code is None:
        check_code = f"""\
import json, sys
context = json.loads(sys.stdin.read())
auto_fix = context.get("auto_fix", False)
result = {{"name": "{name}", "passed": True, "output": "ok", "duration_seconds": 0.1, "detail": None}}
json.dump(result, sys.stdout)
sys.exit(0)
"""
    (folder / "check.py").write_text(check_code)
    return folder


def _make_verifier(
    tmp_path: Path,
    global_plugins: dict[str, dict[str, Any]] | None = None,
    project_plugins: dict[str, dict[str, Any]] | None = None,
) -> Verifier:
    """Build a Verifier with test plugin directories."""
    global_dir = tmp_path / "global_verifications"
    project_dir = tmp_path / "project_verifications"
    global_dir.mkdir(parents=True, exist_ok=True)
    project_dir.mkdir(parents=True, exist_ok=True)

    for name, kwargs in (global_plugins or {}).items():
        _write_plugin(global_dir, name, **kwargs)
    for name, kwargs in (project_plugins or {}).items():
        _write_plugin(project_dir, name, **kwargs)

    return Verifier(
        project_root=tmp_path,
        global_verifications=global_dir,
        project_verifications=project_dir,
    )


# ---------------------------------------------------------------------------
# Manifest: supports_auto_fix field
# ---------------------------------------------------------------------------


class TestManifestAutoFix:
    def test_manifest_loads_supports_auto_fix_true(self, tmp_path: Path) -> None:
        v = _make_verifier(
            tmp_path,
            global_plugins={"lint": {"supports_auto_fix": True}},
        )
        plugins = v.discover_plugins()
        assert len(plugins) == 1
        assert plugins[0].supports_auto_fix is True

    def test_manifest_defaults_supports_auto_fix_false(self, tmp_path: Path) -> None:
        v = _make_verifier(
            tmp_path,
            global_plugins={"lint": {}},
        )
        plugins = v.discover_plugins()
        assert len(plugins) == 1
        assert plugins[0].supports_auto_fix is False


# ---------------------------------------------------------------------------
# auto_fix flag passes through to plugin context
# ---------------------------------------------------------------------------


def _check_code_that_echoes_auto_fix(name: str) -> str:
    """Plugin that reports whether auto_fix was in its context."""
    return f"""\
import json, sys
context = json.loads(sys.stdin.read())
auto_fix = context.get("auto_fix", False)
result = {{
    "name": "{name}",
    "passed": True,
    "output": f"auto_fix={{auto_fix}}",
    "duration_seconds": 0.1,
    "detail": {{"auto_fix_received": auto_fix}},
}}
json.dump(result, sys.stdout)
sys.exit(0)
"""


class TestAutoFixPassthrough:
    def test_auto_fix_true_passed_to_plugin_with_support(self, tmp_path: Path) -> None:
        v = _make_verifier(
            tmp_path,
            global_plugins={
                "fixable": {
                    "supports_auto_fix": True,
                    "check_code": _check_code_that_echoes_auto_fix("fixable"),
                },
            },
        )
        report = asyncio.run(
            v.run_all(
                context={"project_root": str(tmp_path)},
                auto_fix=True,
            )
        )
        assert report.checks[0].detail is not None
        assert report.checks[0].detail["auto_fix_received"] is True

    def test_auto_fix_not_passed_to_plugin_without_support(self, tmp_path: Path) -> None:
        v = _make_verifier(
            tmp_path,
            global_plugins={
                "no_fix": {
                    "supports_auto_fix": False,
                    "check_code": _check_code_that_echoes_auto_fix("no_fix"),
                },
            },
        )
        report = asyncio.run(
            v.run_all(
                context={"project_root": str(tmp_path)},
                auto_fix=True,
            )
        )
        # Plugin without support should NOT receive auto_fix=True
        assert report.checks[0].detail is not None
        assert report.checks[0].detail["auto_fix_received"] is False

    def test_auto_fix_false_by_default(self, tmp_path: Path) -> None:
        v = _make_verifier(
            tmp_path,
            global_plugins={
                "fixable": {
                    "supports_auto_fix": True,
                    "check_code": _check_code_that_echoes_auto_fix("fixable"),
                },
            },
        )
        report = asyncio.run(v.run_all(context={"project_root": str(tmp_path)}))
        assert report.checks[0].detail is not None
        assert report.checks[0].detail["auto_fix_received"] is False


# ---------------------------------------------------------------------------
# lint-ruff plugin auto-fix (integration test with real ruff)
# ---------------------------------------------------------------------------


def _make_ruff_project(tmp_path: Path) -> Path:
    """Create a minimal Python project with a fixable ruff violation."""
    src = tmp_path / "src"
    src.mkdir()
    # Unused import is auto-fixable by ruff
    (src / "bad.py").write_text("import os\n\nx = 1\n")
    # Minimal pyproject for ruff
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\nline-length = 120\n\n[tool.ruff.lint]\nselect = ["F", "I"]\n'
    )
    return tmp_path


class TestLintRuffAutoFix:
    def test_auto_fix_removes_unused_import(self, tmp_path: Path) -> None:
        """When auto_fix=true, lint-ruff should fix the unused import before checking."""
        project = _make_ruff_project(tmp_path)

        # Load the real lint-ruff check.py
        check_path = (
            Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "verifications" / "lint-ruff" / "check.py"
        )
        from importlib.util import module_from_spec, spec_from_file_location

        spec = spec_from_file_location("lint_ruff_check", check_path)
        assert spec is not None
        assert spec.loader is not None
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Run with auto_fix=true by simulating stdin
        import io
        import sys

        context = {"project_root": str(project), "auto_fix": True}
        old_stdin = sys.stdin
        old_stdout = sys.stdout
        sys.stdin = io.StringIO(json.dumps(context))
        captured = io.StringIO()
        sys.stdout = captured

        try:
            with pytest.raises(SystemExit):
                mod.main()
        finally:
            sys.stdin = old_stdin
            sys.stdout = old_stdout

        result = json.loads(captured.getvalue())
        # After auto-fix, the unused import should be gone
        assert result["passed"] is True
        # The file should have been modified on disk
        content = (project / "src" / "bad.py").read_text()
        assert "import os" not in content

    def test_reports_auto_fix_counts(self, tmp_path: Path) -> None:
        """Check that the detail includes auto_fixed_count."""
        project = _make_ruff_project(tmp_path)

        check_path = (
            Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "verifications" / "lint-ruff" / "check.py"
        )
        from importlib.util import module_from_spec, spec_from_file_location

        spec = spec_from_file_location("lint_ruff_check", check_path)
        assert spec is not None
        assert spec.loader is not None
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)

        import io
        import sys

        context = {"project_root": str(project), "auto_fix": True}
        old_stdin = sys.stdin
        old_stdout = sys.stdout
        sys.stdin = io.StringIO(json.dumps(context))
        captured = io.StringIO()
        sys.stdout = captured

        try:
            with pytest.raises(SystemExit):
                mod.main()
        finally:
            sys.stdin = old_stdin
            sys.stdout = old_stdout

        result = json.loads(captured.getvalue())
        assert result["detail"] is not None
        assert result["detail"]["auto_fixed_count"] >= 1
        assert "remaining_count" in result["detail"]


# ---------------------------------------------------------------------------
# CLI --auto-fix flag
# ---------------------------------------------------------------------------


class TestCLIAutoFix:
    def test_auto_fix_flag_accepted(self, monkeypatch) -> None:
        """CLI accepts --auto-fix flag."""
        from unittest.mock import AsyncMock

        from typer.testing import CliRunner

        from ydk.cli import app
        from ydk.models.verification import CheckResult, VerificationReport

        report = VerificationReport(
            timestamp="2026-04-28T00:00:00Z",
            checks=[
                CheckResult(
                    name="lint-ruff",
                    passed=True,
                    output="ok",
                    duration_seconds=0.1,
                    detail={"auto_fixed_count": 3, "remaining_count": 0},
                ),
            ],
            all_passed=True,
            total_duration_seconds=0.3,
        )
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.run_all",
            AsyncMock(return_value=report),
        )
        cli_runner = CliRunner()
        result = cli_runner.invoke(app, ["verify", "run", "--auto-fix"])
        assert result.exit_code == 0

    def test_auto_fix_shows_fix_count(self, monkeypatch) -> None:
        """CLI displays auto-fix count and warning."""
        from unittest.mock import AsyncMock

        from typer.testing import CliRunner

        from ydk.cli import app
        from ydk.models.verification import CheckResult, VerificationReport

        report = VerificationReport(
            timestamp="2026-04-28T00:00:00Z",
            checks=[
                CheckResult(
                    name="lint-ruff",
                    passed=True,
                    output="ok",
                    duration_seconds=0.1,
                    detail={"auto_fixed_count": 5, "remaining_count": 0},
                ),
            ],
            all_passed=True,
            total_duration_seconds=0.3,
        )
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.run_all",
            AsyncMock(return_value=report),
        )
        cli_runner = CliRunner()
        result = cli_runner.invoke(app, ["verify", "run", "--auto-fix"])
        assert result.exit_code == 0
        assert "Auto-fixed 5 issues" in result.output
        assert "0 issues remain" in result.output
        assert "Auto-fix modified files" in result.output

    def test_auto_fix_shows_remaining(self, monkeypatch) -> None:
        """CLI shows remaining issues when auto-fix cannot fix everything."""
        from unittest.mock import AsyncMock

        from typer.testing import CliRunner

        from ydk.cli import app
        from ydk.models.verification import CheckResult, VerificationReport

        report = VerificationReport(
            timestamp="2026-04-28T00:00:00Z",
            checks=[
                CheckResult(
                    name="lint-ruff",
                    passed=False,
                    output="2 errors remain",
                    duration_seconds=0.1,
                    detail={"auto_fixed_count": 3, "remaining_count": 2},
                ),
            ],
            all_passed=False,
            total_duration_seconds=0.3,
        )
        monkeypatch.setattr(
            "ydk.cli.verify_cmd.Verifier.run_all",
            AsyncMock(return_value=report),
        )
        cli_runner = CliRunner()
        result = cli_runner.invoke(app, ["verify", "run", "--auto-fix"])
        assert result.exit_code == 1
        assert "Auto-fixed 3 issues" in result.output
        assert "2 issues remain" in result.output

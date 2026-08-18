"""Tests for ydk verification system (plugin-based core/verifier.py)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from ydk.core.verifier import VerificationContractError, Verifier, _migrate_trigger, _normalize_trigger
from ydk.models.verification import VerificationReport

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
    check_code: str | None = None,
) -> Path:
    """Create a minimal plugin folder with manifest.yaml + check.py."""
    folder = plugin_dir / name
    folder.mkdir(parents=True, exist_ok=True)

    import yaml

    manifest = {
        "name": name,
        "description": f"Test plugin: {name}",
        "trigger": trigger,
        "parallel": parallel,
        "timeout": timeout,
        "requires": requires or [],
    }
    (folder / "manifest.yaml").write_text(yaml.dump(manifest, default_flow_style=False))

    if check_code is None:
        check_code = (
            '''
import json, sys, time
context = json.loads(sys.stdin.read())
result = {"name": "'''
            + name
            + """", "passed": True, "output": "ok", "duration_seconds": 0.1, "detail": None}
json.dump(result, sys.stdout)
sys.exit(0)
"""
        )
    (folder / "check.py").write_text(check_code)
    return folder


def _failing_check_code(name: str) -> str:
    return (
        '''
import json, sys, time
context = json.loads(sys.stdin.read())
result = {"name": "'''
        + name
        + """", "passed": False, "output": "FAILED", "duration_seconds": 0.1, "detail": None}
json.dump(result, sys.stdout)
sys.exit(1)
"""
    )


def _make_verifier(
    tmp_path: Path,
    monkeypatch,
    global_plugins: dict[str, dict[str, Any]] | None = None,
    project_plugins: dict[str, dict[str, Any]] | None = None,
) -> Verifier:
    """Build a Verifier with test plugin directories.

    *global_plugins* and *project_plugins* map plugin name -> kwargs for _write_plugin.
    """
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
# discover_plugins
# ---------------------------------------------------------------------------


class TestDiscoverPlugins:
    def test_discovers_global_plugins(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(tmp_path, monkeypatch, global_plugins={"lint": {}, "types": {}})
        plugins = v.discover_plugins()
        names = {p.name for p in plugins}
        assert "lint" in names
        assert "types" in names

    def test_project_overrides_global(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(
            tmp_path,
            monkeypatch,
            global_plugins={"lint": {"trigger": "git:pre-commit"}},
            project_plugins={"lint": {"trigger": "git:pre-push"}},
        )
        plugins = v.discover_plugins()
        lint_plugins = [p for p in plugins if p.name == "lint"]
        assert len(lint_plugins) == 1
        assert lint_plugins[0].trigger == "git:pre-push"  # project override

    def test_empty_dirs_return_empty(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(tmp_path, monkeypatch)
        assert v.discover_plugins() == []


# ---------------------------------------------------------------------------
# filter methods
# ---------------------------------------------------------------------------


class TestFilters:
    def test_filter_by_trigger(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(
            tmp_path,
            monkeypatch,
            global_plugins={
                "commit_check": {"trigger": "git:pre-commit"},
                "push_check": {"trigger": "git:pre-push"},
            },
        )
        plugins = v.discover_plugins()
        commit = v.filter_by_trigger(plugins, "git:pre-commit")
        assert len(commit) == 1
        assert commit[0].name == "commit_check"

    def test_filter_by_name(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(
            tmp_path,
            monkeypatch,
            global_plugins={"alpha": {}, "beta": {}},
        )
        plugins = v.discover_plugins()
        matched = v.filter_by_name(plugins, "beta")
        assert len(matched) == 1
        assert matched[0].name == "beta"


# ---------------------------------------------------------------------------
# run_plugin
# ---------------------------------------------------------------------------


class TestRunPlugin:
    def test_passing_plugin(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(tmp_path, monkeypatch, global_plugins={"ok_check": {}})
        plugins = v.discover_plugins()
        result = asyncio.run(v.run_plugin(plugins[0], {"project_root": str(tmp_path)}))
        assert result.passed is True
        assert result.name == "ok_check"

    def test_failing_plugin(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(
            tmp_path,
            monkeypatch,
            global_plugins={"bad_check": {"check_code": _failing_check_code("bad_check")}},
        )
        plugins = v.discover_plugins()
        result = asyncio.run(v.run_plugin(plugins[0], {"project_root": str(tmp_path)}))
        assert result.passed is False
        assert "FAILED" in result.output


# ---------------------------------------------------------------------------
# run_layer
# ---------------------------------------------------------------------------


class TestRunLayer:
    def test_runs_parallel_plugins(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(
            tmp_path,
            monkeypatch,
            global_plugins={
                "check_a": {"trigger": "git:pre-commit", "parallel": True},
                "check_b": {"trigger": "git:pre-commit", "parallel": True},
            },
        )
        plugins = v.discover_plugins()
        results = asyncio.run(v.run_layer(plugins, {"project_root": str(tmp_path)}))
        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_runs_serial_plugins(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(
            tmp_path,
            monkeypatch,
            global_plugins={
                "serial_a": {"trigger": "git:pre-commit", "parallel": False},
                "serial_b": {"trigger": "git:pre-commit", "parallel": False},
            },
        )
        plugins = v.discover_plugins()
        results = asyncio.run(v.run_layer(plugins, {"project_root": str(tmp_path)}))
        assert len(results) == 2


# ---------------------------------------------------------------------------
# run_all
# ---------------------------------------------------------------------------


class TestRunAll:
    def test_all_plugins_run_with_no_trigger_filter(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(
            tmp_path,
            monkeypatch,
            global_plugins={"commit_check": {"trigger": "git:pre-commit"}, "push_check": {"trigger": "git:pre-push"}},
        )
        report = asyncio.run(v.run_all(context={"project_root": str(tmp_path)}))
        assert report.all_passed is True
        assert len(report.checks) == 2

    def test_trigger_filter(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(
            tmp_path,
            monkeypatch,
            global_plugins={"commit_only": {"trigger": "git:pre-commit"}, "push_only": {"trigger": "git:pre-push"}},
        )
        report = asyncio.run(v.run_all(trigger="git:pre-commit", context={"project_root": str(tmp_path)}))
        assert len(report.checks) == 1
        assert report.checks[0].name == "commit_only"

    def test_failing_plugin_in_run_all(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(
            tmp_path,
            monkeypatch,
            global_plugins={"fail_check": {"check_code": _failing_check_code("fail_check")}, "pass_check": {}},
        )
        report = asyncio.run(v.run_all(context={"project_root": str(tmp_path)}))
        assert report.all_passed is False
        assert len(report.checks) == 2


# ---------------------------------------------------------------------------
# save_proof
# ---------------------------------------------------------------------------


class TestSaveProof:
    def test_writes_json_to_correct_path(self, tmp_path: Path) -> None:
        v = Verifier(project_root=tmp_path)
        report = VerificationReport(
            timestamp="2026-04-26T00:00:00Z",
            checks=[],
            all_passed=True,
            total_duration_seconds=0.5,
        )
        path = v.save_proof(report)
        assert path == tmp_path / ".ydk" / "proofs" / "verification.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["all_passed"] is True

    def test_creates_task_id_subdirectory(self, tmp_path: Path) -> None:
        v = Verifier(project_root=tmp_path)
        report = VerificationReport(
            timestamp="2026-04-26T00:00:00Z",
            checks=[],
            all_passed=True,
            total_duration_seconds=0.1,
        )
        path = v.save_proof(report, task_id="T-042")
        assert path == tmp_path / ".ydk" / "proofs" / "T-042" / "verification.json"
        assert path.exists()

    def test_creates_directories(self, tmp_path: Path) -> None:
        v = Verifier(project_root=tmp_path)
        report = VerificationReport(
            timestamp="2026-04-26T00:00:00Z",
            checks=[],
            all_passed=False,
            total_duration_seconds=0.0,
        )
        # Ensure no pre-existing .ydk dir
        assert not (tmp_path / ".ydk").exists()
        path = v.save_proof(report)
        assert path.exists()


# ---------------------------------------------------------------------------
# Built-in plugins (integration — verifying the shipped plugins exist)
# ---------------------------------------------------------------------------


class TestBuiltInPlugins:
    def test_global_verifications_directory_exists(self) -> None:
        global_dir = Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "verifications"
        assert global_dir.is_dir(), f"Expected {global_dir} to exist"

    def test_discovers_builtin_plugins(self) -> None:
        """Verifier with no project overrides should find the built-in plugins."""
        global_dir = Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "verifications"
        v = Verifier(
            project_root=Path("."),
            global_verifications=global_dir,
            project_verifications=Path("/nonexistent"),
        )
        plugins = v.discover_plugins()
        names = {p.name for p in plugins}
        assert "lint-ruff" in names
        assert "types-ty" in names
        assert "tests-pytest" in names

    def test_lint_ruff_trigger(self) -> None:
        global_dir = Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "verifications"
        v = Verifier(
            project_root=Path("."),
            global_verifications=global_dir,
            project_verifications=Path("/nonexistent"),
        )
        plugins = v.discover_plugins()
        lint = next(p for p in plugins if p.name == "lint-ruff")
        assert lint.trigger == "git:pre-commit"
        assert lint.parallel is True

    def test_tests_pytest_trigger(self) -> None:
        global_dir = Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "verifications"
        v = Verifier(
            project_root=Path("."),
            global_verifications=global_dir,
            project_verifications=Path("/nonexistent"),
        )
        plugins = v.discover_plugins()
        tests = next(p for p in plugins if p.name == "tests-pytest")
        assert tests.trigger == "git:pre-push"
        assert tests.parallel is False


# ---------------------------------------------------------------------------
# Contract enforcement
# ---------------------------------------------------------------------------


def _invalid_json_check_code() -> str:
    return """\
import sys
sys.stdout.write("this is not json")
sys.exit(0)
"""


def _missing_fields_check_code() -> str:
    return """\
import json, sys
json.dump({"name": "test"}, sys.stdout)
sys.exit(0)
"""


def _exit_code_2_check_code() -> str:
    return """\
import sys
sys.stderr.write("fatal configuration error")
sys.exit(2)
"""


class TestContractEnforcement:
    def test_invalid_json_raises_contract_error(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(
            tmp_path,
            monkeypatch,
            global_plugins={"bad_json": {"check_code": _invalid_json_check_code()}},
        )
        plugins = v.discover_plugins()
        result = asyncio.run(v.run_plugin(plugins[0], {"project_root": str(tmp_path)}))
        assert not result.passed
        assert "invalid json" in result.output.lower()

    def test_missing_output_fields_raises_contract_error(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(
            tmp_path,
            monkeypatch,
            global_plugins={"missing_fields": {"check_code": _missing_fields_check_code()}},
        )
        plugins = v.discover_plugins()
        result = asyncio.run(v.run_plugin(plugins[0], {"project_root": str(tmp_path)}))
        assert not result.passed
        assert "contract" in result.output.lower() or "missing" in result.output.lower()

    def test_exit_code_2_raises_contract_error(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(
            tmp_path,
            monkeypatch,
            global_plugins={"error_plugin": {"check_code": _exit_code_2_check_code()}},
        )
        plugins = v.discover_plugins()
        result = asyncio.run(v.run_plugin(plugins[0], {"project_root": str(tmp_path)}))
        assert not result.passed
        assert "contract" in result.output.lower() or "code 2" in result.output.lower()

    def test_missing_context_fields_raises_contract_error(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(
            tmp_path,
            monkeypatch,
            global_plugins={"check": {}},
        )
        plugins = v.discover_plugins()
        with pytest.raises(VerificationContractError, match="Context missing required fields"):
            asyncio.run(v.run_plugin(plugins[0], {}))


# ---------------------------------------------------------------------------
# Enabled plugin filtering
# ---------------------------------------------------------------------------


class TestEnabledFilter:
    def test_enabled_filter_limits_plugins(self, tmp_path: Path, monkeypatch) -> None:
        global_dir = tmp_path / "global_verifications"
        project_dir = tmp_path / "project_verifications"
        global_dir.mkdir(parents=True, exist_ok=True)
        project_dir.mkdir(parents=True, exist_ok=True)
        _write_plugin(global_dir, "alpha")
        _write_plugin(global_dir, "beta")
        _write_plugin(global_dir, "gamma")

        v = Verifier(
            project_root=tmp_path,
            global_verifications=global_dir,
            project_verifications=project_dir,
            enabled_plugins=["alpha", "gamma"],
        )
        plugins = v.discover_plugins()
        names = {p.name for p in plugins}
        assert names == {"alpha", "gamma"}

    def test_none_enabled_returns_all(self, tmp_path: Path, monkeypatch) -> None:
        global_dir = tmp_path / "global_verifications"
        project_dir = tmp_path / "project_verifications"
        global_dir.mkdir(parents=True, exist_ok=True)
        project_dir.mkdir(parents=True, exist_ok=True)
        _write_plugin(global_dir, "alpha")
        _write_plugin(global_dir, "beta")

        v = Verifier(
            project_root=tmp_path,
            global_verifications=global_dir,
            project_verifications=project_dir,
            enabled_plugins=None,
        )
        plugins = v.discover_plugins()
        assert len(plugins) == 2


class TestMigrateTrigger:
    def test_new_format_passthrough(self) -> None:
        assert _migrate_trigger({"trigger": "git:pre-commit"}) == "git:pre-commit"

    def test_old_list_pre_commit(self) -> None:
        assert _migrate_trigger({"layer": 1, "trigger": ["pre-commit"]}) == "git:pre-commit"

    def test_old_list_pre_push(self) -> None:
        assert _migrate_trigger({"layer": 2, "trigger": ["pre-push"]}) == "git:pre-push"

    def test_old_layer_only_fallback_1(self) -> None:
        assert _migrate_trigger({"layer": 1}) == "git:pre-commit"

    def test_old_layer_only_fallback_2(self) -> None:
        assert _migrate_trigger({"layer": 2}) == "git:pre-push"

    def test_old_layer_3_fallback(self) -> None:
        assert _migrate_trigger({"layer": 3}) == "git:pre-push"

    def test_bare_string_converted(self) -> None:
        assert _migrate_trigger({"trigger": "pre-commit"}) == "git:pre-commit"

    def test_manual_converted(self) -> None:
        assert _migrate_trigger({"trigger": ["manual"]}) == "manual:run"

    def test_old_manifest_loaded_correctly(self, tmp_path: Path, monkeypatch) -> None:
        global_dir = tmp_path / "global_verifications"
        global_dir.mkdir(parents=True, exist_ok=True)
        import yaml

        folder = global_dir / "old-plugin"
        folder.mkdir()
        manifest = {
            "name": "old-plugin",
            "description": "Legacy",
            "layer": 1,
            "trigger": ["pre-commit"],
            "parallel": True,
            "timeout": 30,
            "requires": [],
        }
        (folder / "manifest.yaml").write_text(yaml.dump(manifest, default_flow_style=False))
        (folder / "check.py").write_text(
            "import json,sys;"
            + 'json.dump({"name":"old-plugin","passed":True,"output":"ok","duration_seconds":0.0},sys.stdout)'
        )
        v = Verifier(project_root=tmp_path, global_verifications=global_dir, project_verifications=Path("/nonexistent"))
        plugins = v.discover_plugins()
        assert len(plugins) == 1
        assert plugins[0].trigger == "git:pre-commit"


# ---------------------------------------------------------------------------
# Trigger normalization (shorthand -> canonical)
# ---------------------------------------------------------------------------


class TestNormalizeTrigger:
    def test_pre_commit_shorthand(self) -> None:
        assert _normalize_trigger("pre-commit") == "git:pre-commit"

    def test_pre_push_shorthand(self) -> None:
        assert _normalize_trigger("pre-push") == "git:pre-push"

    def test_manual_stays_manual(self) -> None:
        assert _normalize_trigger("manual") == "manual"

    def test_qualified_passthrough(self) -> None:
        assert _normalize_trigger("git:pre-commit") == "git:pre-commit"

    def test_qualified_pre_push_passthrough(self) -> None:
        assert _normalize_trigger("git:pre-push") == "git:pre-push"

    def test_unknown_shorthand_gets_git_prefix(self) -> None:
        assert _normalize_trigger("post-merge") == "git:post-merge"

    def test_custom_namespace_passthrough(self) -> None:
        assert _normalize_trigger("ci:deploy") == "ci:deploy"


class TestFilterByTriggerShorthand:
    """Ensure filter_by_trigger accepts shorthand triggers."""

    def test_shorthand_pre_commit_matches(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(
            tmp_path,
            monkeypatch,
            global_plugins={
                "commit_check": {"trigger": "git:pre-commit"},
                "push_check": {"trigger": "git:pre-push"},
            },
        )
        plugins = v.discover_plugins()
        commit = v.filter_by_trigger(plugins, "pre-commit")
        assert len(commit) == 1
        assert commit[0].name == "commit_check"

    def test_shorthand_pre_push_matches(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(
            tmp_path,
            monkeypatch,
            global_plugins={
                "commit_check": {"trigger": "git:pre-commit"},
                "push_check": {"trigger": "git:pre-push"},
            },
        )
        plugins = v.discover_plugins()
        push = v.filter_by_trigger(plugins, "pre-push")
        assert len(push) == 1
        assert push[0].name == "push_check"

    def test_run_all_with_shorthand_trigger(self, tmp_path: Path, monkeypatch) -> None:
        v = _make_verifier(
            tmp_path,
            monkeypatch,
            global_plugins={
                "commit_check": {"trigger": "git:pre-commit"},
                "push_check": {"trigger": "git:pre-push"},
            },
        )
        report = asyncio.run(v.run_all(trigger="pre-commit", context={"project_root": str(tmp_path)}))
        assert len(report.checks) == 1
        assert report.checks[0].name == "commit_check"

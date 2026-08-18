"""Tests for P1 bug fixes: spec_refs normalization, runtime deps, task done output, ty scoping."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from ydk.cli.task_cmd import _normalize_refs, _validate_batch_yaml

# ---------------------------------------------------------------------------
# BUG-1: spec_refs parsed character-by-character when string
# ---------------------------------------------------------------------------


class TestNormalizeRefs:
    def test_none_returns_empty(self) -> None:
        assert _normalize_refs(None) == []

    def test_string_returns_single_item_list(self) -> None:
        assert _normalize_refs("01-overview.md") == ["01-overview.md"]

    def test_list_passthrough(self) -> None:
        assert _normalize_refs(["a.md", "b.md"]) == ["a.md", "b.md"]

    def test_integer_wrapped_as_string(self) -> None:
        assert _normalize_refs(42) == ["42"]

    def test_empty_string_returns_single_item(self) -> None:
        assert _normalize_refs("") == [""]

    def test_empty_list_returns_empty(self) -> None:
        assert _normalize_refs([]) == []


class TestBatchYamlStringSpecRefs:
    """Regression: spec_refs as a plain string should not be iterated char-by-char."""

    def test_string_spec_refs_validates_as_single_ref(self, tmp_path: Path) -> None:
        """A batch YAML with spec_refs: 'some-file.md' (string) should treat it as one ref."""
        spec_file = tmp_path / "docs" / "specs" / "01-overview.md"
        spec_file.parent.mkdir(parents=True)
        spec_file.write_text("# Overview")

        data = {
            "tasks": [
                {
                    "id": "T-001",
                    "title": "Test task",
                    "spec_refs": "docs/specs/01-overview.md",  # string, not list
                }
            ]
        }
        errors = _validate_batch_yaml(data, project_root=tmp_path)
        # Should NOT produce errors like "spec_ref '0' not found" (char iteration)
        char_errors = [e for e in errors if "spec_ref '0'" in e or "spec_ref '1'" in e]
        assert char_errors == [], f"Character-level iteration detected: {char_errors}"
        # Should have no errors since the file exists
        assert errors == []

    def test_string_spec_refs_missing_file_reports_single_error(self, tmp_path: Path) -> None:
        """A missing string spec_ref should produce exactly one error, not one per character."""
        data = {
            "tasks": [
                {
                    "id": "T-002",
                    "title": "Test task",
                    "spec_refs": "nonexistent.md",  # string, not list
                }
            ]
        }
        errors = _validate_batch_yaml(data, project_root=tmp_path)
        spec_errors = [e for e in errors if "spec_ref" in e]
        assert len(spec_errors) == 1
        assert "nonexistent.md" in spec_errors[0]

    def test_string_component_refs_in_story(self, tmp_path: Path) -> None:
        """component_refs as a string should also be normalized (no char iteration)."""
        data = {
            "stories": [
                {
                    "id": "S-001",
                    "title": "Test story",
                    "epic": "",
                    "component_refs": "ydk:entity:orders/Order",
                }
            ]
        }
        # Should not raise or produce char-level errors during validation
        errors = _validate_batch_yaml(data, project_root=None)
        assert errors == []


# ---------------------------------------------------------------------------
# BUG-2: Runtime deps not installed by ignition
# ---------------------------------------------------------------------------


class TestIgnitionRuntimeDeps:
    def test_runtime_deps_read_from_manifest(self, tmp_path: Path) -> None:
        """Ignition reads runtime_dependencies from pack manifest and attempts install."""
        from ydk.core.ignition import IgnitionEngine

        # Set up minimal pack
        pack_dir = tmp_path / ".ydk" / "ignition-packs" / "test-pack"
        pack_dir.mkdir(parents=True)
        gen_dir = pack_dir / "generators"
        gen_dir.mkdir()

        # Generator that produces a simple file
        gen_script = gen_dir / "gen.py"
        gen_script.write_text(
            textwrap.dedent("""\
            import json
            print(json.dumps([{"path": "app/__init__.py", "content": "# init"}]))
        """)
        )

        manifest = {
            "runtime_dependencies": {
                "python": ["fastapi>=0.115", "uvicorn>=0.34"],
            },
            "generators": [{"id": "gen", "script": "generators/gen.py", "inputs": []}],
        }
        (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest))

        # Set up components (minimum requirement)
        comp_dir = tmp_path / ".ydk" / "components" / "entity"
        comp_dir.mkdir(parents=True)
        (comp_dir / "Test.yaml").write_text(yaml.dump({"name": "Test"}))

        # Create pyproject.toml so deps install is attempted
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")

        engine = IgnitionEngine(tmp_path)

        with patch("ydk.core.ignition.subprocess.run") as mock_run:
            # First call is the generator, second is py_compile, third is ruff format, etc.
            # We need to mock selectively
            from subprocess import CompletedProcess

            def side_effect(*args: object, **kwargs: object) -> CompletedProcess:  # type: ignore[type-arg]
                cmd = args[0] if args else kwargs.get("args", [])
                if cmd and cmd[0] == "uv" and "add" in cmd:
                    return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
                if cmd and "py_compile" in str(cmd):
                    return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
                if cmd and "ruff" in str(cmd):
                    return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
                # Generator subprocess - let it run for real
                import subprocess

                return subprocess.run(*args, **kwargs)

            mock_run.side_effect = side_effect

            result = engine.ignite()

        assert result.dependencies_installed == ["fastapi>=0.115", "uvicorn>=0.34"]

    def test_runtime_deps_empty_when_not_declared(self, tmp_path: Path) -> None:
        """No runtime_dependencies in manifest -> empty list in result."""
        from ydk.core.ignition import IgnitionEngine

        pack_dir = tmp_path / ".ydk" / "ignition-packs" / "test-pack"
        pack_dir.mkdir(parents=True)
        gen_dir = pack_dir / "generators"
        gen_dir.mkdir()

        gen_script = gen_dir / "gen.py"
        gen_script.write_text(
            textwrap.dedent("""\
            import json
            print(json.dumps([{"path": "app/__init__.py", "content": "# init"}]))
        """)
        )

        manifest = {
            "generators": [{"id": "gen", "script": "generators/gen.py", "inputs": []}],
        }
        (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest))

        comp_dir = tmp_path / ".ydk" / "components" / "entity"
        comp_dir.mkdir(parents=True)
        (comp_dir / "Test.yaml").write_text(yaml.dump({"name": "Test"}))

        engine = IgnitionEngine(tmp_path)
        result = engine.ignite()
        assert result.dependencies_installed == []

    def test_catalog_manifest_has_runtime_deps(self) -> None:
        """The python-fastapi-hexagonal pack manifest declares runtime_dependencies."""
        manifest_path = (
            Path(__file__).resolve().parent.parent.parent
            / "src"
            / "ydk"
            / "catalog"
            / "python-fastapi-hexagonal"
            / "manifest.yaml"
        )
        data = yaml.safe_load(manifest_path.read_text())
        assert "runtime_dependencies" in data
        assert "python" in data["runtime_dependencies"]
        deps = data["runtime_dependencies"]["python"]
        assert any("fastapi" in d for d in deps)


# ---------------------------------------------------------------------------
# BUG-3: ydk task done produces no visible output
# ---------------------------------------------------------------------------


class TestTaskDoneOutput:
    def test_done_success_prints_pass_and_pr(self, tmp_path: Path) -> None:
        """On success, done command prints pass message and PR URL."""
        from typer.testing import CliRunner

        from ydk.cli import app

        runner = CliRunner()

        mock_lc = MagicMock()
        mock_lc.done.return_value = {
            "passed": True,
            "pr_url": "https://github.com/org/repo/pull/42",
            "report": MagicMock(checks=[]),
        }

        # Need todos.yaml for the start precondition check in done
        with patch("ydk.cli.task_cmd._build_lifecycle", return_value=mock_lc):
            result = runner.invoke(app, ["task", "done", "T-001"])

        assert "All verifications passed" in result.output
        assert "https://github.com/org/repo/pull/42" in result.output

    def test_done_failure_prints_check_details(self, tmp_path: Path) -> None:
        """On failure, done command prints individual check results."""
        from typer.testing import CliRunner

        from ydk.cli import app
        from ydk.models.verification import CheckResult, VerificationReport

        runner = CliRunner()

        report = VerificationReport(
            timestamp="2026-05-07T00:00:00Z",
            checks=[
                CheckResult(name="lint-ruff", passed=True, output="OK", duration_seconds=1.2),
                CheckResult(
                    name="types-ty", passed=False, output="error: Type mismatch\nline 42", duration_seconds=3.5
                ),
            ],
            all_passed=False,
            total_duration_seconds=4.7,
        )
        mock_lc = MagicMock()
        mock_lc.done.return_value = {"passed": False, "report": report}

        with patch("ydk.cli.task_cmd._build_lifecycle", return_value=mock_lc):
            result = runner.invoke(app, ["task", "done", "T-001"])

        assert result.exit_code == 1
        assert "Verification failed" in result.output
        assert "lint-ruff" in result.output
        assert "types-ty" in result.output
        assert "Type mismatch" in result.output

    def test_done_exception_prints_error(self, tmp_path: Path) -> None:
        """Lifecycle exceptions are caught and printed clearly."""
        from typer.testing import CliRunner

        from ydk.cli import app

        runner = CliRunner()

        mock_lc = MagicMock()
        mock_lc.done.side_effect = ValueError("Task T-999 not found")

        with patch("ydk.cli.task_cmd._build_lifecycle", return_value=mock_lc):
            result = runner.invoke(app, ["task", "done", "T-999"])

        assert result.exit_code == 1
        assert "T-999 not found" in result.output


# ---------------------------------------------------------------------------
# BUG-4: ty check scoped to changed files
# ---------------------------------------------------------------------------


class TestTyCheckScoping:
    def test_ty_plugin_scopes_to_changed_files(self, tmp_path: Path) -> None:
        """When changed_files is in context, ty only checks those files."""
        check_script = (
            Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "verifications" / "types-ty" / "check.py"
        )
        context = {
            "project_root": str(tmp_path),
            "changed_files": ["src/app/main.py", "src/app/models.py", "README.md"],
        }

        import importlib.util
        import io

        stdin_data = json.dumps(context)
        with (
            patch("subprocess.run") as mock_run,
        ):
            from subprocess import CompletedProcess

            mock_run.return_value = CompletedProcess(args=["ty", "check"], returncode=0, stdout="", stderr="")

            spec = importlib.util.spec_from_file_location("ty_check", str(check_script))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            with (
                patch("sys.stdin", io.StringIO(stdin_data)),
                patch("sys.stdout", new_callable=io.StringIO),
                pytest.raises(SystemExit) as exc_info,
            ):
                module.main()

            assert exc_info.value.code == 0
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "src/app/main.py" in call_args
            assert "src/app/models.py" in call_args
            assert "README.md" not in call_args

    def test_ty_plugin_skips_when_no_py_files_changed(self, tmp_path: Path) -> None:
        """When changed_files has no .py files, ty check is skipped."""
        check_script = (
            Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "verifications" / "types-ty" / "check.py"
        )
        context = {
            "project_root": str(tmp_path),
            "changed_files": ["README.md", "docs/spec.md"],
        }

        import importlib.util
        import io

        spec = importlib.util.spec_from_file_location("ty_check2", str(check_script))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        stdin_data = json.dumps(context)
        with (
            patch("sys.stdin", io.StringIO(stdin_data)),
            patch("sys.stdout", new_callable=io.StringIO) as mock_stdout,
            patch("subprocess.run") as mock_run,
            pytest.raises(SystemExit) as exc_info,
        ):
            module.main()

        assert exc_info.value.code == 0
        mock_run.assert_not_called()
        output = json.loads(mock_stdout.getvalue())
        assert output["passed"] is True
        assert "skipped" in output["output"].lower()

    def test_verifier_injects_changed_files(self) -> None:
        """Verifier._get_changed_files is called and injected into context."""
        from ydk.core.verifier import Verifier

        v = Verifier(project_root=Path("/fake"))
        with patch("subprocess.run") as mock_run:
            from subprocess import CompletedProcess

            mock_run.return_value = CompletedProcess(
                args=["git", "diff"],
                returncode=0,
                stdout="src/app/main.py\nsrc/app/views.py\n",
                stderr="",
            )
            changed = v._get_changed_files()

        assert changed == ["src/app/main.py", "src/app/views.py"]

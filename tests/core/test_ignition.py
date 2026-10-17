"""Tests for the ignition engine."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest
import yaml

from ydk.core.ignition import IgnitionEngine, IgnitionError
from ydk.models.ignition import GeneratedFile, IgnitionResult

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SIMPLE_GENERATOR = textwrap.dedent("""\
    #!/usr/bin/env python3
    \"\"\"Minimal test generator: reads entity components, outputs JSON.\"\"\"
    import json, os, yaml

    entities_path = os.environ.get("YDK_COMPONENTS_ENTITY")
    entities = []
    if entities_path:
        with open(entities_path) as f:
            entities = yaml.safe_load(f) or []

    output = []
    for entity in entities:
        name = entity.get("name", "Unknown")
        output.append({
            "path": f"app/models/{name.lower()}.py",
            "content": f"class {name}:\\n    raise NotImplementedError\\n",
        })

    print(json.dumps(output))
""")

_FAILING_GENERATOR = textwrap.dedent("""\
    #!/usr/bin/env python3
    import sys
    print("something went wrong", file=sys.stderr)
    sys.exit(1)
""")

_EMPTY_GENERATOR = textwrap.dedent("""\
    #!/usr/bin/env python3
    # Produces no output
""")


def _setup_pack(
    root: Path,
    generators: list[dict],
    generator_scripts: dict[str, str] | None = None,
) -> None:
    """Create a minimal ignition pack in root/.ydk/ignition-pack/."""
    pack_dir = root / ".ydk" / "ignition-pack"
    pack_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"name": "test-pack", "version": "0.1.0", "generators": generators}
    (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest, default_flow_style=False))
    if generator_scripts:
        for name, content in generator_scripts.items():
            (pack_dir / name).write_text(content)


def _setup_components(root: Path, components: dict[str, list[dict]]) -> None:
    """Create component YAML files in root/.ydk/components/<type>/."""
    for comp_type, items in components.items():
        type_dir = root / ".ydk" / "components" / comp_type
        type_dir.mkdir(parents=True, exist_ok=True)
        for i, item in enumerate(items):
            (type_dir / f"{item.get('name', f'comp{i}').lower()}.yaml").write_text(
                yaml.dump(item, default_flow_style=False)
            )


# ---------------------------------------------------------------------------
# IgnitionEngine tests
# ---------------------------------------------------------------------------


class TestLoadPack:
    def test_no_pack_returns_none(self, tmp_path: Path) -> None:
        engine = IgnitionEngine(tmp_path)
        assert engine._load_pack() is None

    def test_loads_valid_pack(self, tmp_path: Path) -> None:
        _setup_pack(tmp_path, generators=[{"script": "gen.py"}])
        engine = IgnitionEngine(tmp_path)
        pack = engine._load_pack()
        assert pack is not None
        assert pack["name"] == "test-pack"
        assert len(pack["generators"]) == 1


class TestAssembleComponents:
    def test_empty_when_no_components_dir(self, tmp_path: Path) -> None:
        engine = IgnitionEngine(tmp_path)
        assert engine._assemble_components() == {}

    def test_groups_by_type(self, tmp_path: Path) -> None:
        _setup_components(
            tmp_path,
            {
                "entity": [{"name": "Strategy"}, {"name": "Trade"}],
                "route": [{"name": "create"}, {"name": "list"}],
            },
        )
        engine = IgnitionEngine(tmp_path)
        result = engine._assemble_components()
        assert set(result.keys()) == {"entity", "route"}
        assert len(result["entity"]) == 2
        assert len(result["route"]) == 2

    def test_skips_non_yaml_files(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / ".ydk" / "components" / "entity"
        comp_dir.mkdir(parents=True)
        (comp_dir / "readme.txt").write_text("not yaml")
        (comp_dir / "strategy.yaml").write_text(yaml.dump({"name": "Strategy"}))
        engine = IgnitionEngine(tmp_path)
        result = engine._assemble_components()
        assert len(result["entity"]) == 1

    def test_reads_utf8_regardless_of_locale(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / ".ydk" / "components" / "page"
        comp_dir.mkdir(parents=True)
        # U+2510 encodes to bytes containing 0x90, undefined in cp1252.
        (comp_dir / "main.yaml").write_text("name: main\nwireframe: ┌─┐\n", encoding="utf-8")
        result = IgnitionEngine(tmp_path)._assemble_components()
        assert result["page"][0]["wireframe"] == "┌─┐"


class TestRunGenerator:
    def test_simple_generator_produces_files(self, tmp_path: Path) -> None:
        _setup_pack(
            tmp_path,
            generators=[{"script": "gen.py"}],
            generator_scripts={"gen.py": _SIMPLE_GENERATOR},
        )
        _setup_components(tmp_path, {"entity": [{"name": "Strategy"}]})
        engine = IgnitionEngine(tmp_path)
        component_data = engine._assemble_components()
        script = tmp_path / ".ydk" / "ignition-pack" / "gen.py"
        files = engine._run_generator(script, component_data, tmp_path, {})
        assert len(files) == 1
        assert files[0].path == "app/models/strategy.py"
        assert "class Strategy" in files[0].content

    def test_failing_generator_raises(self, tmp_path: Path) -> None:
        _setup_pack(
            tmp_path,
            generators=[{"script": "fail.py"}],
            generator_scripts={"fail.py": _FAILING_GENERATOR},
        )
        engine = IgnitionEngine(tmp_path)
        script = tmp_path / ".ydk" / "ignition-pack" / "fail.py"
        with pytest.raises(IgnitionError, match="exited with code 1"):
            engine._run_generator(script, {}, tmp_path, {})

    def test_empty_generator_returns_empty_list(self, tmp_path: Path) -> None:
        _setup_pack(
            tmp_path,
            generators=[{"script": "empty.py"}],
            generator_scripts={"empty.py": _EMPTY_GENERATOR},
        )
        engine = IgnitionEngine(tmp_path)
        script = tmp_path / ".ydk" / "ignition-pack" / "empty.py"
        files = engine._run_generator(script, {}, tmp_path, {})
        assert files == []

    def test_component_key_order_preserved(self, tmp_path: Path) -> None:
        # Method params are ordered maps; generators must see manifest order, not sorted keys.
        echo = textwrap.dedent("""\
            import json, os, yaml
            with open(os.environ["YDK_COMPONENTS_CONTRACT"]) as f:
                params = yaml.safe_load(f)[0]["methods"]["publish"]["params"]
            print(json.dumps([{"path": "order.txt", "content": ",".join(params)}]))
        """)
        _setup_pack(tmp_path, generators=[{"script": "echo.py"}], generator_scripts={"echo.py": echo})
        contract = {"methods": {"publish": {"params": {"ctx": {}, "user": {}, "text": {}}}}}
        engine = IgnitionEngine(tmp_path)
        script = tmp_path / ".ydk" / "ignition-pack" / "echo.py"
        files = engine._run_generator(script, {"contract": [contract]}, tmp_path, {})
        assert files[0].content == "ctx,user,text"


class TestRegisterTodos:
    def test_counts_not_implemented_errors(self, tmp_path: Path) -> None:
        engine = IgnitionEngine(tmp_path)
        files = [
            GeneratedFile(
                path="app/svc.py",
                content="class Svc:\n    def run(self):\n        raise NotImplementedError\n",
            ),
            GeneratedFile(
                path="app/other.py",
                content="class Other:\n    pass\n",
            ),
        ]
        assert engine._register_todos(files) == 1

    def test_counts_multiple_in_same_file(self, tmp_path: Path) -> None:
        engine = IgnitionEngine(tmp_path)
        files = [
            GeneratedFile(
                path="app/svc.py",
                content=(
                    "class Svc:\n"
                    "    def a(self):\n        raise NotImplementedError\n"
                    "    def b(self):\n        raise NotImplementedError\n"
                ),
            ),
        ]
        assert engine._register_todos(files) == 2

    def test_ignores_non_python_files(self, tmp_path: Path) -> None:
        engine = IgnitionEngine(tmp_path)
        files = [
            GeneratedFile(path="readme.md", content="raise NotImplementedError"),
        ]
        assert engine._register_todos(files) == 0

    def test_counts_csharp_not_implemented(self, tmp_path: Path) -> None:
        engine = IgnitionEngine(tmp_path)
        files = [
            GeneratedFile(
                path="Services/FooService.cs",
                content=(
                    "public class FooService {\n"
                    "    public void Run() {\n"
                    "        throw new NotImplementedException();\n"
                    "    }\n"
                    "}\n"
                ),
            ),
        ]
        assert engine._register_todos(files) == 1

    def test_counts_go_panic_not_implemented(self, tmp_path: Path) -> None:
        engine = IgnitionEngine(tmp_path)
        files = [
            GeneratedFile(
                path="svc/svc.go",
                content='package svc\n\nfunc Run() {\n\tpanic("not implemented") // YDK-TODO-001: impl\n}\n',
            ),
        ]
        assert engine._register_todos(files) == 1
        from ydk.core.todo_manager import TodoManager

        todo = TodoManager(tmp_path).list_todos()[0]
        assert (todo.file, todo.line) == ("svc/svc.go", 4)

    def test_go_marker_records_enclosing_func_and_receiver(self, tmp_path: Path) -> None:
        from ydk.core.todo_manager import TodoManager

        engine = IgnitionEngine(tmp_path)
        content = (
            "package svc\n\n"
            'func Run() {\n\tpanic("not implemented") // YDK-TODO-001: a\n}\n\n'
            'func (s *Svc) Handle(x int) error {\n\tpanic("not implemented") // YDK-TODO-002: b\n}\n\n'
            'func (Svc) Plain() {\n\tpanic("not implemented") // YDK-TODO-003: c\n}\n'
            'func (s Repo[T]) Get() {\n\tpanic("not implemented") // YDK-TODO-004: d\n}\n'
        )
        engine._register_todos([GeneratedFile(path="svc/svc.go", content=content)])
        methods = sorted(t.method for t in TodoManager(tmp_path).list_todos())
        assert methods == ["Repo.Get", "Run", "Svc.Handle", "Svc.Plain"]

    def test_go_legacy_unknown_entry_survives_shift(self, tmp_path: Path) -> None:
        from ydk.core.todo_manager import TodoManager

        mgr = TodoManager(tmp_path)
        mgr.reconcile("svc/svc.go", [{"line": 4, "method": "<unknown>", "description": "YDK-TODO-001: impl"}])
        before = [t.id for t in mgr.list_todos()]
        content = 'package svc\n\n// c\n// c\nfunc Run() {\n\tpanic("not implemented") // YDK-TODO-001: impl\n}\n'
        IgnitionEngine(tmp_path)._register_todos([GeneratedFile(path="svc/svc.go", content=content)])
        todos = mgr.list_todos()
        assert [t.id for t in todos] == before
        assert todos[0].method == "Run"

    def test_reignite_moved_marker_leaves_one_entry(self, tmp_path: Path) -> None:
        from ydk.core.todo_manager import TodoManager

        engine = IgnitionEngine(tmp_path)
        old = "class Svc:\n    def run(self):\n        raise NotImplementedError\n"
        moved = "# header\n# header\n" + old
        engine._register_todos([GeneratedFile(path="app/svc.py", content=old)])
        engine._register_todos([GeneratedFile(path="app/svc.py", content=moved)])
        todos = TodoManager(tmp_path).list_todos()
        assert [(t.line, t.status.value) for t in todos] == [(5, "open")]

    def test_reignite_removed_marker_is_resolved(self, tmp_path: Path) -> None:
        from ydk.core.todo_manager import TodoManager

        engine = IgnitionEngine(tmp_path)
        old = "class Svc:\n    def run(self):\n        raise NotImplementedError\n"
        engine._register_todos([GeneratedFile(path="app/svc.py", content=old)])
        engine._register_todos([GeneratedFile(path="app/svc.py", content="class Svc:\n    pass\n")])
        todos = TodoManager(tmp_path).list_todos()
        assert [t.status.value for t in todos] == ["done"]


class TestIgniteFull:
    def test_ignite_no_pack_raises(self, tmp_path: Path) -> None:
        engine = IgnitionEngine(tmp_path)
        with pytest.raises(IgnitionError, match="No ignition pack found"):
            engine.ignite()

    def test_ignite_end_to_end(self, tmp_path: Path) -> None:
        """Full pipeline: components -> generator -> files on disk."""
        _setup_pack(
            tmp_path,
            generators=[{"script": "gen.py"}],
            generator_scripts={"gen.py": _SIMPLE_GENERATOR},
        )
        _setup_components(tmp_path, {"entity": [{"name": "Strategy"}, {"name": "Trade"}]})

        engine = IgnitionEngine(tmp_path)
        result = engine.ignite()

        assert result.files_generated == 2
        assert result.files_written == 2
        assert result.files_skipped == 0
        assert result.todos_registered == 2
        assert not result.errors

        # Files actually exist
        assert (tmp_path / "app" / "models" / "strategy.py").exists()
        assert (tmp_path / "app" / "models" / "trade.py").exists()

        # Files are written with their content (no header prepended)
        content = (tmp_path / "app" / "models" / "strategy.py").read_text()
        assert "class Strategy" in content

    def test_ignite_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        _setup_pack(
            tmp_path,
            generators=[{"script": "gen.py"}],
            generator_scripts={"gen.py": _SIMPLE_GENERATOR},
        )
        _setup_components(tmp_path, {"entity": [{"name": "Strategy"}]})

        engine = IgnitionEngine(tmp_path)
        result = engine.ignite(dry_run=True)

        assert result.files_generated == 1
        assert result.files_written == 1  # would-be-written count
        assert not (tmp_path / "app" / "models" / "strategy.py").exists()

    def test_ignite_idempotent_second_run_skips(self, tmp_path: Path) -> None:
        """Running ignite twice skips unchanged files."""
        _setup_pack(
            tmp_path,
            generators=[{"script": "gen.py"}],
            generator_scripts={"gen.py": _SIMPLE_GENERATOR},
        )
        _setup_components(tmp_path, {"entity": [{"name": "Strategy"}]})

        engine = IgnitionEngine(tmp_path)
        r1 = engine.ignite()
        assert r1.files_written == 1

        r2 = engine.ignite()
        assert r2.files_generated == 1
        assert r2.files_written == 0
        assert r2.files_skipped == 1

    def test_ignite_skips_developer_owned_file(self, tmp_path: Path) -> None:
        """Files manually edited by developer are not overwritten."""
        _setup_pack(
            tmp_path,
            generators=[{"script": "gen.py"}],
            generator_scripts={"gen.py": _SIMPLE_GENERATOR},
        )
        _setup_components(tmp_path, {"entity": [{"name": "Strategy"}]})

        # First ignite creates the file
        engine = IgnitionEngine(tmp_path)
        engine.ignite()

        # Developer removes the GENERATED header (takes ownership)
        f = tmp_path / "app" / "models" / "strategy.py"
        f.write_text("# My custom code\nclass Strategy:\n    pass\n")

        # Second ignite should skip it
        r2 = engine.ignite()
        assert r2.files_skipped == 1
        assert any("developer-owned" in w for w in r2.warnings)

    def test_ignite_force_overwrites_developer_owned(self, tmp_path: Path) -> None:
        """--force regenerates even developer-owned files."""
        _setup_pack(
            tmp_path,
            generators=[{"script": "gen.py"}],
            generator_scripts={"gen.py": _SIMPLE_GENERATOR},
        )
        _setup_components(tmp_path, {"entity": [{"name": "Strategy"}]})

        engine = IgnitionEngine(tmp_path)
        engine.ignite()

        # Developer edits
        f = tmp_path / "app" / "models" / "strategy.py"
        f.write_text("# Custom\nclass Strategy:\n    pass\n")

        r2 = engine.ignite(force=True)
        assert r2.files_written == 1
        assert r2.files_skipped == 0

        # File got regenerated with content
        assert "class Strategy" in f.read_text()

    def test_ignite_generator_error_captured(self, tmp_path: Path) -> None:
        """A failing generator produces an error but doesn't crash the engine."""
        _setup_pack(
            tmp_path,
            generators=[
                {"script": "fail.py"},
                {"script": "gen.py"},
            ],
            generator_scripts={
                "fail.py": _FAILING_GENERATOR,
                "gen.py": _SIMPLE_GENERATOR,
            },
        )
        _setup_components(tmp_path, {"entity": [{"name": "Strategy"}]})

        engine = IgnitionEngine(tmp_path)
        result = engine.ignite()

        assert len(result.errors) == 1
        assert "fail.py" in result.errors[0]
        # The good generator still ran
        assert result.files_generated == 1

    def test_ignite_missing_generator_script_captured(self, tmp_path: Path) -> None:
        """A missing generator script is captured as an error."""
        _setup_pack(
            tmp_path,
            generators=[{"script": "nonexistent.py"}],
        )
        _setup_components(tmp_path, {"entity": [{"name": "Placeholder"}]})
        engine = IgnitionEngine(tmp_path)
        result = engine.ignite()
        assert len(result.errors) == 1
        assert "not found" in result.errors[0]

    def test_ignite_with_init_answers(self, tmp_path: Path) -> None:
        """init_answers are passed to generators via YDK_INIT_ANSWERS."""
        gen_with_answers = textwrap.dedent("""\
            #!/usr/bin/env python3
            import json, os
            answers = json.loads(os.environ.get("YDK_INIT_ANSWERS", "{}"))
            name = answers.get("project_name", "default")
            print(json.dumps([{"path": "app/config.py", "content": f"PROJECT = '{name}'\\n"}]))
        """)
        _setup_pack(
            tmp_path,
            generators=[{"script": "gen.py"}],
            generator_scripts={"gen.py": gen_with_answers},
        )
        _setup_components(tmp_path, {"entity": [{"name": "Placeholder"}]})

        engine = IgnitionEngine(tmp_path)
        result = engine.ignite(init_answers={"project_name": "myapp"})

        assert result.files_written == 1
        content = (tmp_path / "app" / "config.py").read_text()
        assert "myapp" in content


class TestNoComponents:
    def test_ignite_no_components_raises(self, tmp_path: Path) -> None:
        """ignite with pack but no components raises clear error."""
        _setup_pack(
            tmp_path,
            generators=[{"script": "gen.py"}],
            generator_scripts={"gen.py": _SIMPLE_GENERATOR},
        )
        # No components set up — components dir is empty or missing
        engine = IgnitionEngine(tmp_path)
        with pytest.raises(IgnitionError, match="No components found"):
            engine.ignite()


class TestGeneratorStderrLogging:
    def test_stderr_on_success_logged(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Generator stderr output on success is logged as warning."""
        gen_with_stderr = textwrap.dedent("""\
            #!/usr/bin/env python3
            import json, sys
            print("Warning: deprecated feature used", file=sys.stderr)
            print(json.dumps([]))
        """)
        _setup_pack(
            tmp_path,
            generators=[{"script": "gen.py"}],
            generator_scripts={"gen.py": gen_with_stderr},
        )
        engine = IgnitionEngine(tmp_path)
        component_data = {"entity": [{"name": "Foo"}]}
        script = tmp_path / ".ydk" / "ignition-pack" / "gen.py"

        import logging

        with caplog.at_level(logging.WARNING, logger="ydk.ignition"):
            engine._run_generator(script, component_data, tmp_path, {})

        assert any("stderr" in r.message.lower() or "deprecated" in r.message.lower() for r in caplog.records)


class TestGeneratorTimeout:
    def test_timeout_raises_ignition_error(self, tmp_path: Path) -> None:
        """subprocess.TimeoutExpired is wrapped in IgnitionError."""
        import subprocess as sp
        from unittest.mock import patch

        _setup_pack(
            tmp_path,
            generators=[{"script": "slow.py"}],
            generator_scripts={"slow.py": "# placeholder"},
        )
        engine = IgnitionEngine(tmp_path)
        script = tmp_path / ".ydk" / "ignition-pack" / "slow.py"

        with patch("ydk.core.ignition.subprocess.run") as mock_run:
            mock_run.side_effect = sp.TimeoutExpired(cmd=["python", "slow.py"], timeout=120)
            with pytest.raises(IgnitionError, match=r"(?i)timeout|timed out"):
                engine._run_generator(script, {}, tmp_path, {})


class TestDetectImportCycles:
    def test_detects_cycle(self, tmp_path: Path) -> None:
        """Two files that import each other produce a cycle warning."""
        a = tmp_path / "module_a.py"
        b = tmp_path / "module_b.py"
        a.write_text("import module_b\n")
        b.write_text("import module_a\n")

        engine = IgnitionEngine(tmp_path)
        cycles = engine._detect_import_cycles([a, b])
        assert len(cycles) >= 1
        assert "module_a" in cycles[0] or "module_b" in cycles[0]

    def test_no_cycle_clean(self, tmp_path: Path) -> None:
        """Clean files with no circular deps report nothing."""
        a = tmp_path / "module_a.py"
        b = tmp_path / "module_b.py"
        a.write_text("import os\n")
        b.write_text("import sys\n")

        engine = IgnitionEngine(tmp_path)
        cycles = engine._detect_import_cycles([a, b])
        assert cycles == []

    def test_syntax_error_skipped(self, tmp_path: Path) -> None:
        """Files with syntax errors are skipped, not crash."""
        bad = tmp_path / "broken.py"
        bad.write_text("def broken(\n")

        engine = IgnitionEngine(tmp_path)
        cycles = engine._detect_import_cycles([bad])
        assert cycles == []


class TestRuffFormatCall:
    def test_ruff_called_on_py_files(self, tmp_path: Path) -> None:
        """Post-generate calls ruff format on generated .py files."""
        from unittest.mock import patch

        good_py = tmp_path / "good.py"
        good_py.write_text("x = 1\n")
        non_py = tmp_path / "data.yaml"
        non_py.write_text("key: val\n")

        engine = IgnitionEngine(tmp_path)

        with patch("ydk.core.ignition.subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})()
            engine._post_generate([good_py, non_py])

            # Find the ruff format call (first arg of the command list is "ruff")
            ruff_calls = [c for c in mock_run.call_args_list if c.args[0][0] == "ruff"]  # type: ignore[union-attr]
            assert len(ruff_calls) == 1
            ruff_cmd = ruff_calls[0].args[0]
            assert ruff_cmd[0] == "ruff"
            assert ruff_cmd[1] == "format"
            assert str(good_py) in ruff_cmd
            assert str(non_py) not in ruff_cmd


class TestPostGenerate:
    def test_syntax_error_detected(self, tmp_path: Path) -> None:
        """Post-generate catches Python syntax errors."""
        bad_py = tmp_path / "bad.py"
        bad_py.write_text("def broken(\n")

        engine = IgnitionEngine(tmp_path)
        errors = engine._post_generate([bad_py])
        assert len(errors) == 1
        assert "Syntax error" in errors[0]

    def test_valid_file_no_errors(self, tmp_path: Path) -> None:
        """Valid Python files produce no errors."""
        good_py = tmp_path / "good.py"
        good_py.write_text("x = 1\n")

        engine = IgnitionEngine(tmp_path)
        errors = engine._post_generate([good_py])
        assert not errors


class TestNewPacksDirectory:
    """Tests for the corrected .ydk/ignition-packs/<name>/ path (Bug 1 fix)."""

    def test_loads_pack_from_ignition_packs_subdir(self, tmp_path: Path) -> None:
        """Pack installed via catalog (plural path with name subdir) is found."""
        pack_dir = tmp_path / ".ydk" / "ignition-packs" / "my-pack"
        pack_dir.mkdir(parents=True)
        manifest = {"name": "my-pack", "version": "1.0.0", "generators": [{"script": "gen.py"}]}
        (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest))
        (pack_dir / "gen.py").write_text(_SIMPLE_GENERATOR)

        _setup_components(tmp_path, {"entity": [{"name": "Foo"}]})
        engine = IgnitionEngine(tmp_path)
        result = engine.ignite()
        assert result.files_generated == 1
        assert not result.errors

    def test_multiple_packs_raises_error(self, tmp_path: Path) -> None:
        """Multiple installed packs cause a clear error."""
        packs_dir = tmp_path / ".ydk" / "ignition-packs"
        for name in ("pack-a", "pack-b"):
            d = packs_dir / name
            d.mkdir(parents=True)
            (d / "manifest.yaml").write_text(yaml.dump({"name": name, "generators": []}))

        _setup_components(tmp_path, {"entity": [{"name": "Foo"}]})
        engine = IgnitionEngine(tmp_path)
        with pytest.raises(IgnitionError, match="Multiple ignition packs"):
            engine.ignite()


class TestYdkComponentEnvVars:
    """Tests: YDK_COMPONENTS_* env vars set for generators."""

    def test_ydk_entity_env_set(self, tmp_path: Path) -> None:
        """Generator sees YDK_COMPONENTS_ENTITY pointing to raw entity list."""
        gen_check = textwrap.dedent("""\
            #!/usr/bin/env python3
            import json, os, yaml
            entity_path = os.environ.get("YDK_COMPONENTS_ENTITY", "")
            assert entity_path, "YDK_COMPONENTS_ENTITY not set"
            data = yaml.safe_load(open(entity_path))
            assert isinstance(data, list), f"Expected list, got {type(data)}"
            assert len(data) == 1
            assert data[0]["name"] == "Widget"
            print(json.dumps([{"path": "ok.txt", "content": "native"}]))
        """)
        pack_dir = tmp_path / ".ydk" / "ignition-packs" / "test-pack"
        pack_dir.mkdir(parents=True)
        manifest = {"name": "test-pack", "version": "0.1.0", "generators": [{"script": "gen.py"}]}
        (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest))
        (pack_dir / "gen.py").write_text(gen_check)

        _setup_components(tmp_path, {"entity": [{"name": "Widget"}]})
        engine = IgnitionEngine(tmp_path)
        result = engine.ignite()
        assert not result.errors
        assert result.files_written == 1

    def test_ydk_contract_env_set(self, tmp_path: Path) -> None:
        """Generator sees YDK_COMPONENTS_CONTRACT pointing to raw contract list."""
        gen_check = textwrap.dedent("""\
            #!/usr/bin/env python3
            import json, os, yaml
            contract_path = os.environ.get("YDK_COMPONENTS_CONTRACT", "")
            assert contract_path, "YDK_COMPONENTS_CONTRACT not set"
            data = yaml.safe_load(open(contract_path))
            assert isinstance(data, list), f"Expected list, got {type(data)}"
            assert len(data) == 1
            assert data[0]["name"] == "OrderService"
            assert len(data[0]["ports"]) == 2
            print(json.dumps([{"path": "ok.txt", "content": "ok"}]))
        """)
        pack_dir = tmp_path / ".ydk" / "ignition-packs" / "test-pack"
        pack_dir.mkdir(parents=True)
        manifest = {"name": "test-pack", "version": "0.1.0", "generators": [{"script": "gen.py"}]}
        (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest))
        (pack_dir / "gen.py").write_text(gen_check)

        _setup_components(
            tmp_path,
            {
                "contract": [{"name": "OrderService", "ports": [{"name": "repo"}, {"name": "notifier"}]}],
            },
        )
        engine = IgnitionEngine(tmp_path)
        result = engine.ignite()
        assert not result.errors
        assert result.files_written == 1


class TestModels:
    def test_generated_file_model(self) -> None:
        gf = GeneratedFile(path="app/main.py", content="print('hi')")
        assert gf.path == "app/main.py"
        assert gf.content == "print('hi')"

    def test_ignition_result_model(self) -> None:
        result = IgnitionResult(
            files_generated=5,
            files_written=3,
            files_skipped=2,
            todos_registered=4,
            errors=["err1"],
            warnings=["warn1"],
            duration_seconds=1.5,
        )
        assert result.files_generated == 5
        assert result.files_skipped == 2
        assert len(result.errors) == 1


# ---------------------------------------------------------------------------
# Bug fix tests
# ---------------------------------------------------------------------------

_CONFLICT_GENERATOR_A = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json
    print(json.dumps([{"path": "app/shared.py", "content": "# from generator A\\n"}]))
""")

_CONFLICT_GENERATOR_B = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json
    print(json.dumps([{"path": "app/shared.py", "content": "# from generator B\\n"}]))
""")


class TestDetectPathConflicts:
    def test_detect_path_conflicts(self, tmp_path: Path) -> None:
        """Two generators producing the same path results in error and dedup."""
        _setup_pack(
            tmp_path,
            generators=[{"script": "gen_a.py"}, {"script": "gen_b.py"}],
            generator_scripts={
                "gen_a.py": _CONFLICT_GENERATOR_A,
                "gen_b.py": _CONFLICT_GENERATOR_B,
            },
        )
        _setup_components(tmp_path, {"entity": [{"name": "Placeholder"}]})

        engine = IgnitionEngine(tmp_path)
        result = engine.ignite()

        # Conflict reported as warning (not error) since files were still written
        assert any("Conflict" in w and "app/shared.py" in w for w in result.warnings)
        # Warning about skipping duplicate
        assert any("Skipping duplicate" in w for w in result.warnings)
        # Only one file written (the first one wins)
        assert result.files_written == 1
        content = (tmp_path / "app" / "shared.py").read_text()
        assert "generator A" in content

    def test_no_conflict_no_error(self, tmp_path: Path) -> None:
        """No conflicts when generators produce different paths."""
        engine = IgnitionEngine(tmp_path)
        files = [
            GeneratedFile(path="a.py", content="x"),
            GeneratedFile(path="b.py", content="y"),
        ]
        conflicts = engine._detect_conflicts(files)
        assert conflicts == []


class TestSingletonComponentUnwrapping:
    def test_singleton_component_unwrapping(self, tmp_path: Path) -> None:
        """Config with 1 item gets YDK_COMPONENT_CONFIG (singular, unwrapped dict)."""
        gen_check_singular = textwrap.dedent("""\
            #!/usr/bin/env python3
            import json, os, yaml

            # Plural should exist and be a list
            plural_path = os.environ.get("YDK_COMPONENTS_CONFIG", "")
            assert plural_path, "YDK_COMPONENTS_CONFIG not set"
            plural_data = yaml.safe_load(open(plural_path))
            assert isinstance(plural_data, list), f"Plural should be list, got {type(plural_data)}"

            # Singular should exist and be a dict (unwrapped)
            singular_path = os.environ.get("YDK_COMPONENT_CONFIG", "")
            assert singular_path, "YDK_COMPONENT_CONFIG not set"
            singular_data = yaml.safe_load(open(singular_path))
            assert isinstance(singular_data, dict), f"Singular should be dict, got {type(singular_data)}"
            assert singular_data["title"] == "MyApp"

            print(json.dumps([{"path": "ok.txt", "content": "singleton works"}]))
        """)
        pack_dir = tmp_path / ".ydk" / "ignition-packs" / "test-pack"
        pack_dir.mkdir(parents=True)
        manifest = {"name": "test-pack", "version": "0.1.0", "generators": [{"script": "gen.py"}]}
        (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest))
        (pack_dir / "gen.py").write_text(gen_check_singular)

        _setup_components(tmp_path, {"config": [{"title": "MyApp", "version": "1.0"}]})
        engine = IgnitionEngine(tmp_path)
        result = engine.ignite()
        assert not result.errors, f"Errors: {result.errors}"
        assert result.files_written == 1

    def test_no_singular_for_multiple_components(self, tmp_path: Path) -> None:
        """When >1 component of a type, no singular env var is set."""
        gen_check_no_singular = textwrap.dedent("""\
            #!/usr/bin/env python3
            import json, os

            # Plural should exist
            assert os.environ.get("YDK_COMPONENTS_ENTITY"), "Plural not set"
            # Singular should NOT exist (multiple entities)
            assert not os.environ.get("YDK_COMPONENT_ENTITY"), "Singular should not be set for multiple"

            print(json.dumps([{"path": "ok.txt", "content": "ok"}]))
        """)
        pack_dir = tmp_path / ".ydk" / "ignition-packs" / "test-pack"
        pack_dir.mkdir(parents=True)
        manifest = {"name": "test-pack", "version": "0.1.0", "generators": [{"script": "gen.py"}]}
        (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest))
        (pack_dir / "gen.py").write_text(gen_check_no_singular)

        _setup_components(tmp_path, {"entity": [{"name": "A"}, {"name": "B"}]})
        engine = IgnitionEngine(tmp_path)
        result = engine.ignite()
        assert not result.errors, f"Errors: {result.errors}"


class TestTodoPersistence:
    def test_todo_persistence(self, tmp_path: Path) -> None:
        """After ignition, TODOs are registered in the registry file."""
        _setup_pack(
            tmp_path,
            generators=[{"script": "gen.py"}],
            generator_scripts={"gen.py": _SIMPLE_GENERATOR},
        )
        _setup_components(tmp_path, {"entity": [{"name": "Strategy"}]})

        # Ensure .ydk dir exists for the todo registry
        (tmp_path / ".ydk").mkdir(parents=True, exist_ok=True)

        engine = IgnitionEngine(tmp_path)
        result = engine.ignite()

        assert result.todos_registered >= 1

        # Verify TODOs are actually persisted via TodoManager
        from ydk.core.todo_manager import TodoManager

        todo_mgr = TodoManager(tmp_path)
        todos = todo_mgr.list_todos()
        assert len(todos) >= 1
        assert todos[0].file == "app/models/strategy.py"


# ---------------------------------------------------------------------------
# Phased ignition tests
# ---------------------------------------------------------------------------

_PHASE_GENERATOR_A = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json
    print(json.dumps([
        {"path": "models/item.py", "content": "class Item:\\n    pass\\n"},
    ]))
""")

_PHASE_GENERATOR_B = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json, os
    artifact = os.environ.get("YDK_ARTIFACT_OPENAPI", "not-set")
    print(json.dumps([
        {"path": "client/api.ts", "content": f"// artifact: {artifact}\\n"},
    ]))
""")

_PHASE_GENERATOR_INFRA = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json
    print(json.dumps([
        {"path": "docker-compose.yml", "content": "version: '3.9'\\n"},
    ]))
""")


def _setup_phased_pack(
    root: Path,
    phases: list[dict],
    generator_scripts: dict[str, str] | None = None,
) -> None:
    """Create a phased ignition pack in root/.ydk/ignition-pack/."""
    pack_dir = root / ".ydk" / "ignition-pack"
    pack_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"name": "phased-pack", "version": "0.1.0", "phases": phases}
    (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest, default_flow_style=False))
    if generator_scripts:
        for name, content in generator_scripts.items():
            script_path = pack_dir / name
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text(content)


class TestPhasedIgnitionRunsInOrder:
    def test_phases_run_sequentially(self, tmp_path: Path) -> None:
        """Phases run in declaration order and all produce output."""
        _setup_phased_pack(
            tmp_path,
            phases=[
                {
                    "id": "phase-a",
                    "generators": [{"script": "gen_a.py"}],
                },
                {
                    "id": "phase-b",
                    "generators": [{"script": "gen_b.py"}],
                },
            ],
            generator_scripts={
                "gen_a.py": _PHASE_GENERATOR_A,
                "gen_b.py": _PHASE_GENERATOR_INFRA,
            },
        )
        _setup_components(tmp_path, {"entity": [{"name": "Item"}]})

        engine = IgnitionEngine(tmp_path)
        result = engine.ignite()

        assert result.files_generated == 2
        assert not result.errors
        assert (tmp_path / "models" / "item.py").exists()
        assert (tmp_path / "docker-compose.yml").exists()


class TestPhasedIgnitionWithTopLevelGenerators:
    def test_top_level_generators_run_before_phases(self, tmp_path: Path) -> None:
        """Top-level generators run alongside phases, before them."""
        _setup_phased_pack(
            tmp_path,
            phases=[{"id": "ops", "generators": [{"script": "gen_b.py"}]}],
            generator_scripts={
                "gen_a.py": _PHASE_GENERATOR_A,
                "gen_b.py": _PHASE_GENERATOR_INFRA,
            },
        )
        manifest_path = tmp_path / ".ydk" / "ignition-pack" / "manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text())
        manifest["generators"] = [{"script": "gen_a.py"}]
        manifest_path.write_text(yaml.dump(manifest, default_flow_style=False))
        _setup_components(tmp_path, {"entity": [{"name": "Item"}]})

        result = IgnitionEngine(tmp_path).ignite()

        assert not result.errors
        assert result.files_generated == 2
        assert (tmp_path / "models" / "item.py").exists()
        assert (tmp_path / "docker-compose.yml").exists()


class TestPhasedIgnitionArtifactPassing:
    def test_artifacts_passed_between_phases(self, tmp_path: Path) -> None:
        """Artifacts exported from phase A are available as env vars in phase B."""
        # Create a fake export file that phase A would produce
        export_file = tmp_path / "backend" / "dist" / "openapi.json"
        export_file.parent.mkdir(parents=True)
        export_file.write_text('{"openapi": "3.0.0"}')

        _setup_phased_pack(
            tmp_path,
            phases=[
                {
                    "id": "backend",
                    "generators": [{"script": "gen_a.py"}],
                    "exports": {"openapi": "backend/dist/openapi.json"},
                },
                {
                    "id": "frontend",
                    "depends_on": ["backend"],
                    "artifacts": {"openapi": "${backend.openapi}"},
                    "generators": [{"script": "gen_b.py"}],
                },
            ],
            generator_scripts={
                "gen_a.py": _PHASE_GENERATOR_A,
                "gen_b.py": _PHASE_GENERATOR_B,
            },
        )
        _setup_components(tmp_path, {"entity": [{"name": "Item"}]})

        engine = IgnitionEngine(tmp_path)
        result = engine.ignite()

        assert not result.errors
        assert result.files_generated == 2
        # Check that the artifact was passed to phase B
        api_content = (tmp_path / "client" / "api.ts").read_text()
        assert str(export_file) in api_content


class TestPhasedIgnitionOutputPrefix:
    def test_output_prefix_prepended(self, tmp_path: Path) -> None:
        """output_prefix is prepended to all generated file paths."""
        _setup_phased_pack(
            tmp_path,
            phases=[
                {
                    "id": "backend",
                    "output_prefix": "backend/",
                    "generators": [{"script": "gen_a.py"}],
                },
                {
                    "id": "infra",
                    "output_prefix": "infra/",
                    "generators": [{"script": "gen_infra.py"}],
                },
            ],
            generator_scripts={
                "gen_a.py": _PHASE_GENERATOR_A,
                "gen_infra.py": _PHASE_GENERATOR_INFRA,
            },
        )
        _setup_components(tmp_path, {"entity": [{"name": "Item"}]})

        engine = IgnitionEngine(tmp_path)
        result = engine.ignite()

        assert not result.errors
        assert (tmp_path / "backend" / "models" / "item.py").exists()
        assert (tmp_path / "infra" / "docker-compose.yml").exists()


class TestPhasedIgnitionWithPackRef:
    def test_pack_ref_loads_generators_from_referenced_pack(self, tmp_path: Path) -> None:
        """pack_ref causes the engine to load generators from another installed pack."""
        # Set up the main phased pack in ignition-packs (single subdir = the main pack)
        pack_dir = tmp_path / ".ydk" / "ignition-packs" / "phased-pack"
        pack_dir.mkdir(parents=True)
        manifest = {
            "name": "phased-pack",
            "version": "0.1.0",
            "phases": [
                {
                    "id": "backend",
                    "pack_ref": "ref-pack",
                    "output_prefix": "backend/",
                },
                {
                    "id": "infra",
                    "generators": [{"script": "gen_infra.py"}],
                },
            ],
        }
        (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest))
        (pack_dir / "gen_infra.py").write_text(_PHASE_GENERATOR_INFRA)

        # Set up a referenced pack in a separate catalog-like location
        # We'll create it where _find_installed_pack can find it: in the catalog source
        # Since we can't easily inject into the installed package, use a monkeypatch approach
        # Instead, place it at a known path and patch _find_installed_pack
        ref_pack_dir = tmp_path / "_catalog" / "ref-pack"
        ref_pack_dir.mkdir(parents=True)
        ref_manifest = {
            "name": "ref-pack",
            "version": "1.0.0",
            "generators": [{"script": "gen.py"}],
        }
        (ref_pack_dir / "manifest.yaml").write_text(yaml.dump(ref_manifest))
        (ref_pack_dir / "gen.py").write_text(_PHASE_GENERATOR_A)

        _setup_components(tmp_path, {"entity": [{"name": "Item"}]})

        engine = IgnitionEngine(tmp_path)
        # Patch _find_installed_pack to find ref-pack from our test location
        original_find = engine._find_installed_pack

        def patched_find(pack_name: str):
            if pack_name == "ref-pack":
                return ref_pack_dir
            return original_find(pack_name)

        engine._find_installed_pack = patched_find  # type: ignore[method-assign]
        result = engine.ignite()

        assert not result.errors, f"Errors: {result.errors}"
        # Referenced pack's generator output with prefix
        assert (tmp_path / "backend" / "models" / "item.py").exists()
        # Local generator output
        assert (tmp_path / "docker-compose.yml").exists()

    def test_pack_ref_not_found_errors(self, tmp_path: Path) -> None:
        """Missing pack_ref produces a clear error."""
        _setup_phased_pack(
            tmp_path,
            phases=[
                {
                    "id": "missing",
                    "pack_ref": "nonexistent-pack",
                },
            ],
        )
        _setup_components(tmp_path, {"entity": [{"name": "Item"}]})

        engine = IgnitionEngine(tmp_path)
        result = engine.ignite()

        assert any("nonexistent-pack" in e and "not found" in e for e in result.errors)


class TestFlatManifestBackwardCompat:
    def test_flat_manifest_still_works(self, tmp_path: Path) -> None:
        """A manifest with only 'generators' (no 'phases') still works as before."""
        _setup_pack(
            tmp_path,
            generators=[{"script": "gen.py"}],
            generator_scripts={"gen.py": _SIMPLE_GENERATOR},
        )
        _setup_components(tmp_path, {"entity": [{"name": "Strategy"}]})

        engine = IgnitionEngine(tmp_path)
        result = engine.ignite()

        assert result.files_generated == 1
        assert result.files_written == 1
        assert not result.errors
        assert (tmp_path / "app" / "models" / "strategy.py").exists()


def _fake_run(returncode: int = 0, stderr: str = "", stdout: str = ""):
    return type("R", (), {"returncode": returncode, "stderr": stderr, "stdout": stdout})()


class TestGoPostGenerate:
    def test_gofmt_then_build_and_vet(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        go_file = tmp_path / "main.go"
        go_file.write_text("package main\n")
        other = tmp_path / "README.md"
        other.write_text("x\n")
        engine = IgnitionEngine(tmp_path)

        with patch("ydk.core.ignition.subprocess.run", return_value=_fake_run()) as mock_run:
            errors = engine._post_generate_go([go_file, other])

        assert errors == []
        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert cmds[0] == ["gofmt", "-w", str(go_file)]
        assert ["go", "build", "./..."] in cmds
        assert ["go", "vet", "./..."] in cmds
        assert not any(c[0] in ("ruff", "uv") for c in cmds)

    def test_build_failure_reports_output(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        go_file = tmp_path / "main.go"
        go_file.write_text("package main\n")
        engine = IgnitionEngine(tmp_path)

        def run(cmd, **_kw):
            if cmd[:2] == ["go", "build"]:
                return _fake_run(1, stderr="import cycle not allowed")
            return _fake_run()

        with patch("ydk.core.ignition.subprocess.run", side_effect=run):
            errors = engine._post_generate_go([go_file])

        assert len(errors) == 1
        assert "go build" in errors[0]
        assert "import cycle not allowed" in errors[0]

    def test_no_go_files_runs_nothing(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        engine = IgnitionEngine(tmp_path)
        with patch("ydk.core.ignition.subprocess.run") as mock_run:
            assert engine._post_generate_go([]) == []
        mock_run.assert_not_called()


class TestGoRuntimeDeps:
    def test_get_tidy_vendor(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        (tmp_path / "go.mod").write_text("module x\n")
        engine = IgnitionEngine(tmp_path)
        pack = {"runtime_dependencies": {"go": ["github.com/twmb/franz-go@v1.22.1"]}}
        warnings: list[str] = []

        with patch("ydk.core.ignition.subprocess.run", return_value=_fake_run()) as mock_run:
            installed = engine._install_go_deps(pack, warnings)

        assert installed == ["github.com/twmb/franz-go@v1.22.1"]
        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert cmds == [
            ["go", "get", "github.com/twmb/franz-go@v1.22.1"],
            ["go", "mod", "tidy"],
            ["go", "mod", "vendor"],
        ]
        assert warnings == []

    def test_no_deps_noop(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        engine = IgnitionEngine(tmp_path)
        with patch("ydk.core.ignition.subprocess.run") as mock_run:
            assert engine._install_go_deps({}, []) == []
        mock_run.assert_not_called()

    def test_installs_modules_required_by_generated_go_mod(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        (tmp_path / "go.mod").write_text(
            "module x\n\ngo 1.22\n\nrequire (\n\tgithub.com/twmb/franz-go v1.22.1\n\tc/d v0.2.0 // indirect\n)\n"
        )
        engine = IgnitionEngine(tmp_path)
        warnings: list[str] = []
        with patch("ydk.core.ignition.subprocess.run", return_value=_fake_run()) as mock_run:
            installed = engine._install_go_deps({"runtime_dependencies": {"go": ["a/b@v1.0.0"]}}, warnings)

        assert installed == ["a/b@v1.0.0", "github.com/twmb/franz-go@v1.22.1"]
        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert cmds[0] == ["go", "get", *installed]
        assert warnings == []

    def test_single_line_require_without_pack_deps(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        (tmp_path / "go.mod").write_text("module x\n\nrequire github.com/twmb/franz-go v1.22.1\n")
        engine = IgnitionEngine(tmp_path)
        with patch("ydk.core.ignition.subprocess.run", return_value=_fake_run()) as mock_run:
            installed = engine._install_go_deps({}, [])
        assert installed == ["github.com/twmb/franz-go@v1.22.1"]
        assert [c.args[0][:2] for c in mock_run.call_args_list] == [["go", "get"], ["go", "mod"], ["go", "mod"]]

    def test_pack_pin_wins_over_go_mod_version(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        (tmp_path / "go.mod").write_text("module x\n\nrequire(\n\ta/b v0.9.0\n)\n")
        engine = IgnitionEngine(tmp_path)
        with patch("ydk.core.ignition.subprocess.run", return_value=_fake_run()):
            installed = engine._install_go_deps({"runtime_dependencies": {"go": ["a/b@v1.0.0"]}}, [])
        assert installed == ["a/b@v1.0.0"]

    def test_go_mod_without_requires_is_noop(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        (tmp_path / "go.mod").write_text("module x\n\ngo 1.22\n")
        engine = IgnitionEngine(tmp_path)
        with patch("ydk.core.ignition.subprocess.run") as mock_run:
            assert engine._install_go_deps({}, []) == []
        mock_run.assert_not_called()

    def test_missing_go_mod_warns(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        engine = IgnitionEngine(tmp_path)
        warnings: list[str] = []
        with patch("ydk.core.ignition.subprocess.run") as mock_run:
            out = engine._install_go_deps({"runtime_dependencies": {"go": ["a/b@v1.0.0"]}}, warnings)
        assert out == []
        assert warnings
        mock_run.assert_not_called()

    def test_failure_warns(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        (tmp_path / "go.mod").write_text("module x\n")
        engine = IgnitionEngine(tmp_path)
        warnings: list[str] = []
        with patch("ydk.core.ignition.subprocess.run", return_value=_fake_run(1, stderr="boom")):
            out = engine._install_go_deps({"runtime_dependencies": {"go": ["a/b@v1.0.0"]}}, warnings)
        assert out == []
        assert "boom" in warnings[0]


class TestGoIgniteDispatch:
    def test_go_pack_skips_python_steps(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        engine = IgnitionEngine(tmp_path)
        with (
            patch.object(engine, "_post_generate_go", return_value=["go build failed"]) as go_post,
            patch.object(engine, "_post_generate") as py_post,
            patch.object(engine, "_install_go_deps", return_value=[]) as go_deps,
            patch.object(engine, "_install_runtime_deps") as py_deps,
        ):
            errors, installed = engine._run_post_steps({"stack": {"language": "go"}}, [tmp_path / "a.go"], [])
        assert errors == ["go build failed"]
        assert installed == []
        go_post.assert_called_once()
        go_deps.assert_called_once()
        py_post.assert_not_called()
        py_deps.assert_not_called()


class TestGoReigniteAfterGofmt:
    def test_gofmt_rewrite_not_treated_as_developer_edit(self, tmp_path: Path) -> None:
        import subprocess as real_subprocess
        from pathlib import Path
        from unittest.mock import patch

        gen = textwrap.dedent("""\
            import json
            body = "package main\\nfunc main()  {\\n" + "\\tpanic(\\"not implemented\\")\\n}\\n"
            files = [{"path": "main.go", "content": body}, {"path": "go.mod", "content": "module x\\n"}]
            print(json.dumps(files))
        """)
        pack_dir = tmp_path / ".ydk" / "ignition-pack"
        pack_dir.mkdir(parents=True)
        manifest = {
            "name": "go-pack",
            "stack": {"language": "go"},
            "runtime_dependencies": {"go": ["example.com/dep@v1.0.0"]},
            "generators": [{"script": "gen.py"}],
        }
        (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest))
        (pack_dir / "gen.py").write_text(gen)
        _setup_components(tmp_path, {"entity": [{"name": "X"}]})
        real_run = real_subprocess.run

        def run(cmd, **kw):
            if cmd[0] == "gofmt":  # simulate gofmt rewriting the file
                for f in cmd[2:]:
                    Path(f).write_text('package main\n\nfunc main() {\n\tpanic("not implemented")\n}\n')
                return _fake_run()
            if cmd[:2] == ["go", "get"]:  # simulate go get adding a require line to go.mod
                with (tmp_path / "go.mod").open("a") as fh:
                    fh.write("require example.com/dep v1.0.0\n")
                return _fake_run()
            if cmd[0] == "go":
                return _fake_run()
            return real_run(cmd, **kw)

        with patch("ydk.core.ignition.subprocess.run", side_effect=run):
            IgnitionEngine(tmp_path).ignite()
            second = IgnitionEngine(tmp_path).ignite()
            forced = IgnitionEngine(tmp_path).ignite(force=True)
        assert not any("developer-owned" in w for w in second.warnings)
        # Unchanged generator output: nothing rewritten, no TODO registered twice.
        assert second.files_written == 0
        assert second.todos_registered == 0
        # A forced rewrite re-scans the same TODO location: reused, not counted as new.
        assert forced.files_written == 2
        assert forced.todos_registered == 0
        todos = yaml.safe_load((tmp_path / ".ydk" / "todos.yaml").read_text())["todos"]
        assert len(todos) == 1


class TestGoMissingToolchain:
    def test_post_generate_missing_go_reports_error(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        go_file = tmp_path / "main.go"
        go_file.write_text("package main\n")
        engine = IgnitionEngine(tmp_path)
        with patch("ydk.core.ignition.subprocess.run", side_effect=FileNotFoundError("go")):
            errors = engine._post_generate_go([go_file])
        assert errors
        assert all("not runnable" in e for e in errors)

    def test_install_deps_missing_go_warns(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        (tmp_path / "go.mod").write_text("module x\n")
        engine = IgnitionEngine(tmp_path)
        warnings: list[str] = []
        with patch("ydk.core.ignition.subprocess.run", side_effect=FileNotFoundError("go")):
            out = engine._install_go_deps({"runtime_dependencies": {"go": ["a/b@v1.0.0"]}}, warnings)
        assert out == []
        assert warnings


class TestLineEndings:
    def test_generated_files_written_with_lf(self, tmp_path: Path) -> None:
        _setup_pack(
            tmp_path,
            generators=[{"script": "gen.py"}],
            generator_scripts={"gen.py": _SIMPLE_GENERATOR},
        )
        _setup_components(tmp_path, {"entity": [{"name": "Strategy"}]})

        IgnitionEngine(tmp_path).ignite()

        data = (tmp_path / "app" / "models" / "strategy.py").read_bytes()
        assert b"\n" in data
        assert b"\r\n" not in data

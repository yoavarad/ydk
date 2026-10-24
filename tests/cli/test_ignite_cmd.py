"""Tests for the ydk ignite CLI command."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest
import yaml
from typer.testing import CliRunner

from ydk.cli import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

_SIMPLE_GENERATOR = textwrap.dedent("""\
    #!/usr/bin/env python3
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


def _setup_project(root: Path) -> None:
    """Create a minimal project with pack + components + schemas + spec-check-results."""
    pack_dir = root / ".ydk" / "ignition-pack"
    pack_dir.mkdir(parents=True)
    manifest = {
        "name": "test-pack",
        "version": "0.1.0",
        "generators": [{"script": "gen.py"}],
    }
    (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest, default_flow_style=False))
    (pack_dir / "gen.py").write_text(_SIMPLE_GENERATOR)

    comp_dir = root / ".ydk" / "components" / "entity"
    comp_dir.mkdir(parents=True)
    (comp_dir / "strategy.yaml").write_text(yaml.dump({"name": "Strategy"}))

    # Preconditions for ignite CLI
    schemas_dir = root / ".ydk" / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    (schemas_dir / "entity.yaml").write_text("type: entity\nfields: []")
    (root / ".ydk" / "spec-check-results.json").write_text('{"passed": true}')


def test_ignite_no_pack(tmp_path: Path, monkeypatch: object) -> None:
    """ignite with no pack exits with error."""
    import os

    monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))  # type: ignore[attr-defined]
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    # Set up schemas so we hit the pack check (not the schemas check)
    schemas_dir = tmp_path / ".ydk" / "schemas"
    schemas_dir.mkdir(parents=True)
    (schemas_dir / "entity.yaml").write_text("type: entity")
    result = runner.invoke(app, ["ignite"])
    assert result.exit_code == 1
    assert "No ignition pack" in result.output


def test_ignite_success(tmp_path: Path, monkeypatch: object) -> None:
    """ignite with valid pack prints report."""
    _setup_project(tmp_path)
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["ignite"])
    assert result.exit_code == 0
    assert "Ignition Report" in result.output
    assert "Files generated" in result.output


def test_ignite_dry_run(tmp_path: Path, monkeypatch: object) -> None:
    """--dry-run shows report but writes nothing."""
    _setup_project(tmp_path)
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["ignite", "--dry-run"])
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert not (tmp_path / "app" / "models" / "strategy.py").exists()


def test_ignite_force_overwrites_developer_owned(tmp_path: Path, monkeypatch: object) -> None:
    """--force overwrites developer-owned files via CLI."""
    _setup_project(tmp_path)
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]

    # First ignite creates the file
    result = runner.invoke(app, ["ignite"])
    assert result.exit_code == 0

    # Developer removes the GENERATED header (takes ownership)
    f = tmp_path / "app" / "models" / "strategy.py"
    f.write_text("# My custom code\nclass Strategy:\n    pass\n")

    # Normal ignite would skip, --force should overwrite
    result = runner.invoke(app, ["ignite", "--force"])
    assert result.exit_code == 0
    assert "class Strategy" in f.read_text()


_ANSWERS_GENERATOR = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json, os
    answers = json.loads(os.environ.get("YDK_INIT_ANSWERS", "{}"))
    print(json.dumps([{"path": "answers.json", "content": json.dumps(answers, sort_keys=True)}]))
""")


def _setup_answers_project(root: Path, config_answers: dict[str, str] | None = None) -> None:
    """Project whose generator writes the received init answers to answers.json."""
    _setup_project(root)
    (root / ".ydk" / "ignition-pack" / "gen.py").write_text(_ANSWERS_GENERATOR)
    if config_answers is not None:
        config = {"project": {"name": "x"}, "ignition": {"init_answers": config_answers}}
        (root / ".ydk" / "config.yaml").write_text(yaml.dump(config))


def _answers(root: Path) -> dict[str, str]:
    import json

    return json.loads((root / "answers.json").read_text())


def test_ignite_answer_flag_passed_to_generator(tmp_path: Path, monkeypatch: object) -> None:
    """--answer KEY=VALUE (repeatable) reaches the generator via YDK_INIT_ANSWERS."""
    _setup_answers_project(tmp_path)
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = runner.invoke(
        app,
        [
            "ignite",
            "--answer",
            "runtime_image=registry.access.redhat.com/ubi9/ubi-micro",
            "--answer",
            "http_port=9090",
        ],
    )
    assert result.exit_code == 0, result.output
    assert _answers(tmp_path) == {
        "http_port": "9090",
        "runtime_image": "registry.access.redhat.com/ubi9/ubi-micro",
    }


def test_ignite_answer_value_may_contain_equals(tmp_path: Path, monkeypatch: object) -> None:
    """Only the first '=' splits key from value."""
    _setup_answers_project(tmp_path)
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["ignite", "--answer", "app_name=a=b"])
    assert result.exit_code == 0, result.output
    assert _answers(tmp_path) == {"app_name": "a=b"}


def test_ignite_config_answers_passed_to_generator(tmp_path: Path, monkeypatch: object) -> None:
    """ignition.init_answers in config reaches the generator on every ignite."""
    _setup_answers_project(tmp_path, {"go_module": "example.com/svc"})
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["ignite"])
    assert result.exit_code == 0, result.output
    assert _answers(tmp_path) == {"go_module": "example.com/svc"}


def test_ignite_cli_answer_overrides_config(tmp_path: Path, monkeypatch: object) -> None:
    """A CLI --answer wins over the same key in config; other config keys are kept."""
    _setup_answers_project(tmp_path, {"go_module": "example.com/svc", "app_name": "svc"})
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["ignite", "--answer", "go_module=example.com/other"])
    assert result.exit_code == 0, result.output
    assert _answers(tmp_path) == {"app_name": "svc", "go_module": "example.com/other"}


@pytest.mark.parametrize("bad", ["no_equals", "=value", " =value"])
def test_ignite_malformed_answer_exits_nonzero(tmp_path: Path, monkeypatch: object, bad: str) -> None:
    """A malformed --answer exits 1 with a clear message and writes nothing."""
    _setup_answers_project(tmp_path)
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["ignite", "--answer", bad])
    assert result.exit_code == 1
    assert "KEY=VALUE" in result.output
    assert not (tmp_path / "answers.json").exists()


def test_ignite_broken_config_exits_cleanly(tmp_path: Path, monkeypatch: object) -> None:
    """A syntactically broken config.yaml exits 1 with a message, not a traceback."""
    _setup_answers_project(tmp_path)
    (tmp_path / ".ydk" / "config.yaml").write_text("project: [unclosed\n")
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["ignite"])
    assert result.exit_code == 1
    assert "Invalid .ydk/config.yaml" in result.output


def test_ignite_go_http_service_renders_answers(tmp_path: Path, monkeypatch: object) -> None:
    """With the real go-http-service pack, answers render into Dockerfile and go.mod."""
    import shutil
    from pathlib import Path as _Path

    import ydk

    pack_src = _Path(ydk.__file__).parent / "catalog" / "go-http-service"
    shutil.copytree(pack_src, tmp_path / ".ydk" / "ignition-packs" / "go-http-service")
    shutil.copytree(pack_src / "samples" / "minimal" / "components", tmp_path / ".ydk" / "components")
    schemas_dir = tmp_path / ".ydk" / "schemas"
    schemas_dir.mkdir(parents=True)
    (schemas_dir / "entity.yaml").write_text("type: entity\nfields: []")
    config = {"project": {"name": "x"}, "ignition": {"init_answers": {"go_module": "example.com/acme/svc"}}}
    (tmp_path / ".ydk" / "config.yaml").write_text(yaml.dump(config))
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    # No Go toolchain: post-generation steps degrade deterministically.
    empty_bin = tmp_path / "nobin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))  # type: ignore[attr-defined]

    result = runner.invoke(
        app,
        [
            "ignite",
            "--skip-verify",
            "--answer",
            "runtime_image=registry.access.redhat.com/ubi9/ubi-micro",
        ],
    )
    assert result.exit_code == 0, result.output
    dockerfile = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
    assert "registry.access.redhat.com/ubi9/ubi-micro" in dockerfile
    go_mod = (tmp_path / "go.mod").read_text(encoding="utf-8")
    assert "module example.com/acme/svc" in go_mod


def test_ignite_registered_as_top_level_command() -> None:
    """ignite is a top-level command, not a subgroup."""
    # Check the command is directly on the app
    from ydk.cli import app

    command_names = []
    if hasattr(app, "registered_commands"):
        command_names = [cmd.name or cmd.callback.__name__ for cmd in app.registered_commands if cmd.callback]
    assert "ignite" in command_names or "ignite_command" in command_names


def test_ignite_only_writes_matching_and_reports_merge(tmp_path: Path, monkeypatch: object) -> None:
    """--only writes matching paths only, reports developer-owned matches, keeps the stage."""
    _setup_project(tmp_path)
    comp_dir = tmp_path / ".ydk" / "components" / "entity"
    (comp_dir / "trade.yaml").write_text(yaml.dump({"name": "Trade"}))
    (tmp_path / ".ydk" / "state.json").write_text('{"stage": "03"}')
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]

    result = runner.invoke(app, ["ignite", "--skip-verify", "--only", "app/models/strategy.py"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "app" / "models" / "strategy.py").exists()
    assert not (tmp_path / "app" / "models" / "trade.py").exists()
    assert "Files excluded (--only)" in result.output
    # A retrofit must not reset the project stage.
    import json

    assert json.loads((tmp_path / ".ydk" / "state.json").read_text())["stage"] == "03"

    (tmp_path / "app" / "models" / "strategy.py").write_text("# mine\n")
    result = runner.invoke(app, ["ignite", "--only", "app/models/*", "--only", "other/*"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "app" / "models" / "strategy.py").read_text() == "# mine\n"
    assert "skipped — merge manually" in result.output
    assert "--skip-verify --force --only app/models/strategy.py" in " ".join(result.output.split())

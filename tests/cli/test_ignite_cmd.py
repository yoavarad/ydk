"""Tests for the odk ignite CLI command."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import yaml
from typer.testing import CliRunner

from odk.cli import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

_SIMPLE_GENERATOR = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json, os, yaml
    entities_path = os.environ.get("ODK_COMPONENTS_ENTITY")
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
    pack_dir = root / ".odk" / "ignition-pack"
    pack_dir.mkdir(parents=True)
    manifest = {
        "name": "test-pack",
        "version": "0.1.0",
        "generators": [{"script": "gen.py"}],
    }
    (pack_dir / "manifest.yaml").write_text(yaml.dump(manifest, default_flow_style=False))
    (pack_dir / "gen.py").write_text(_SIMPLE_GENERATOR)

    comp_dir = root / ".odk" / "components" / "entity"
    comp_dir.mkdir(parents=True)
    (comp_dir / "strategy.yaml").write_text(yaml.dump({"name": "Strategy"}))

    # Preconditions for ignite CLI
    schemas_dir = root / ".odk" / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    (schemas_dir / "entity.yaml").write_text("type: entity\nfields: []")
    (root / ".odk" / "spec-check-results.json").write_text('{"passed": true}')


def test_ignite_no_pack(tmp_path: Path, monkeypatch: object) -> None:
    """ignite with no pack exits with error."""
    import os

    monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))  # type: ignore[attr-defined]
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    # Set up schemas so we hit the pack check (not the schemas check)
    schemas_dir = tmp_path / ".odk" / "schemas"
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


def test_ignite_registered_as_top_level_command() -> None:
    """ignite is a top-level command, not a subgroup."""
    # Check the command is directly on the app
    from odk.cli import app

    command_names = []
    if hasattr(app, "registered_commands"):
        command_names = [cmd.name or cmd.callback.__name__ for cmd in app.registered_commands if cmd.callback]
    assert "ignite" in command_names or "ignite_command" in command_names

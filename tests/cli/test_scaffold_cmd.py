"""Tests for ydk scaffold commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from typer.testing import CliRunner

from ydk.cli import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _create_template(base: Path, name: str, variables: dict[str, str], files: dict[str, str]) -> Path:
    """Helper: create a template folder with manifest and .j2 files."""
    folder = base / name
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "description": f"Test template {name}", "variables": variables}
    (folder / "manifest.yaml").write_text(yaml.dump(manifest, default_flow_style=False))
    for filename, content in files.items():
        file_path = folder / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
    return folder


def test_scaffold_list_shows_templates(tmp_path: Path, monkeypatch: object) -> None:
    """ydk scaffold list shows available templates."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    project_templates = tmp_path / ".ydk" / "templates"
    _create_template(project_templates, "my-tmpl", {"x": "X var"}, {"f.txt.j2": "hello"})

    result = runner.invoke(app, ["scaffold", "list"])
    assert result.exit_code == 0
    assert "my-tmpl" in result.output


def test_scaffold_info_shows_manifest(tmp_path: Path, monkeypatch: object) -> None:
    """ydk scaffold info test-greeting shows manifest."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    project_templates = tmp_path / ".ydk" / "templates"
    _create_template(project_templates, "demo", {"greeting": "The greeting"}, {"f.txt.j2": "hi"})

    result = runner.invoke(app, ["scaffold", "info", "demo"])
    assert result.exit_code == 0
    assert "demo" in result.output
    assert "greeting" in result.output


def test_scaffold_apply_generates_files(tmp_path: Path, monkeypatch: object) -> None:
    """ydk scaffold apply with --var generates files."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    project_templates = tmp_path / ".ydk" / "templates"
    _create_template(
        project_templates,
        "greet",
        {"name": "Name"},
        {"hello.txt.j2": "Hello, {{name}}!"},
    )

    output_dir = tmp_path / "output"
    result = runner.invoke(
        app,
        [
            "scaffold",
            "apply",
            "greet",
            "--var",
            "name=World",
            "--output-dir",
            str(output_dir),
        ],
    )
    assert result.exit_code == 0
    assert "Generated" in result.output
    assert (output_dir / "hello.txt").exists()
    assert "Hello, World!" in (output_dir / "hello.txt").read_text()


def test_scaffold_apply_without_variables_exits_error(tmp_path: Path, monkeypatch: object) -> None:
    """ydk scaffold apply without required variables exits with error."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    project_templates = tmp_path / ".ydk" / "templates"
    _create_template(
        project_templates,
        "needs-vars",
        {"a": "A var", "b": "B var"},
        {"f.txt.j2": "{{a}} {{b}}"},
    )

    result = runner.invoke(app, ["scaffold", "apply", "needs-vars"])
    assert result.exit_code != 0
    assert "Missing" in result.output


def test_scaffold_create_creates_template_dir(tmp_path: Path, monkeypatch: object) -> None:
    """ydk scaffold create my-template creates template dir."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]

    result = runner.invoke(app, ["scaffold", "create", "my-template", "-d", "A test template"])
    assert result.exit_code == 0
    assert "Created" in result.output

    manifest_path = tmp_path / ".ydk" / "templates" / "my-template" / "manifest.yaml"
    assert manifest_path.exists()
    data = yaml.safe_load(manifest_path.read_text())
    assert data["name"] == "my-template"
    assert data["description"] == "A test template"

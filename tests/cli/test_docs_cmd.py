"""Tests for ydk docs generate CLI command."""

from __future__ import annotations

from typer.testing import CliRunner

from ydk.cli import app

runner = CliRunner()


def _live_command_names() -> list[str]:
    import click
    import typer.main

    cmd = typer.main.get_command(app)
    assert isinstance(cmd, click.Group)
    return sorted(n for n, c in cmd.commands.items() if not c.hidden)


def test_docs_generate_creates_expected_files(tmp_path) -> None:
    """ydk docs generate produces CLI reference and schema MDX files."""
    output_dir = tmp_path / "_generated"

    result = runner.invoke(app, ["docs", "generate", "--output", str(output_dir)])

    assert result.exit_code == 0, result.output

    # CLI reference pages: one per live top-level command (except docs itself)
    expected_cli_pages = [name for name in _live_command_names() if name != "docs"]
    assert "catalog" in expected_cli_pages
    for page in expected_cli_pages:
        mdx = output_dir / "cli" / f"{page}.mdx"
        assert mdx.exists(), f"Missing CLI page: {mdx}"
        content = mdx.read_text(encoding="utf-8")
        assert content.startswith("---"), f"Missing frontmatter in {page}.mdx"
        assert f"ydk {page}" in content

    # Schema reference page
    schemas_mdx = output_dir / "schemas.mdx"
    assert schemas_mdx.exists(), "Missing schemas.mdx"
    content = schemas_mdx.read_text(encoding="utf-8")
    assert "Component Schemas" in content
    # Should contain at least the entity and route schemas
    assert "entity" in content
    assert "route" in content


def test_docs_generate_cli_pages_have_code_blocks(tmp_path) -> None:
    """Generated CLI pages contain help text in code blocks."""
    output_dir = tmp_path / "_generated"
    runner.invoke(app, ["docs", "generate", "--output", str(output_dir)])

    init_mdx = output_dir / "cli" / "init.mdx"
    content = init_mdx.read_text(encoding="utf-8")
    assert "```text" in content
    assert "```" in content


def test_docs_generate_group_pages_have_subcommands(tmp_path) -> None:
    """Group command pages include subcommand sections."""
    output_dir = tmp_path / "_generated"
    result = runner.invoke(app, ["docs", "generate", "--output", str(output_dir)])
    assert result.exit_code == 0, result.output

    component_mdx = output_dir / "cli" / "component.mdx"
    content = component_mdx.read_text(encoding="utf-8")
    # component has subcommands — each rendered as ## `ydk component <sub>`
    # Match any subcommand heading (e.g. list, show, validate)
    import re

    subcommand_headings = re.findall(r"^## `ydk component \w+`", content, re.MULTILINE)
    assert len(subcommand_headings) >= 1, (
        f"Expected at least one subcommand heading in component.mdx, found none. Content preview:\n{content[:500]}"
    )


def test_docs_generate_schemas_contain_yaml(tmp_path) -> None:
    """Schema page contains YAML code blocks from schema files."""
    output_dir = tmp_path / "_generated"
    runner.invoke(app, ["docs", "generate", "--output", str(output_dir)])

    schemas_mdx = output_dir / "schemas.mdx"
    content = schemas_mdx.read_text(encoding="utf-8")
    assert "```yaml" in content


def test_docs_generate_output_count(tmp_path) -> None:
    """Generate reports the correct number of files."""
    output_dir = tmp_path / "_generated"
    result = runner.invoke(app, ["docs", "generate", "--output", str(output_dir)])
    expected = len([n for n in _live_command_names() if n != "docs"]) + 1
    assert f"{expected} files generated" in result.output


def test_docs_generate_has_no_stale_pages(tmp_path) -> None:
    """Pages exist only for commands that are registered in the live app."""
    output_dir = tmp_path / "_generated"
    runner.invoke(app, ["docs", "generate", "--output", str(output_dir)])
    pages = {p.stem for p in (output_dir / "cli").glob("*.mdx")}
    assert pages == {n for n in _live_command_names() if n != "docs"}
    assert not pages & {"checkpoint", "quickdev", "status"}


def test_discover_cli_pages_kinds() -> None:
    """Page kinds and exclusions are pinned explicitly."""
    from ydk.cli.docs_cmd import _discover_cli_pages

    pages = _discover_cli_pages()
    assert pages["task"] == {"kind": "group"}
    assert pages["ci"] == {"kind": "group"}
    assert pages["init"] == {"kind": "standalone"}
    assert "docs" not in pages
    assert "quickdev" not in pages


def test_docs_generate_writes_meta_json(tmp_path) -> None:
    """cli/meta.json lists exactly the generated pages."""
    import json

    output_dir = tmp_path / "_generated"
    runner.invoke(app, ["docs", "generate", "--output", str(output_dir)])
    meta = json.loads((output_dir / "cli" / "meta.json").read_text(encoding="utf-8"))
    assert meta["pages"] == sorted(p.stem for p in (output_dir / "cli").glob("*.mdx"))

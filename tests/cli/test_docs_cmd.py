"""Tests for odk docs generate CLI command."""

from __future__ import annotations

from typer.testing import CliRunner

from odk.cli import app

runner = CliRunner()


def test_docs_generate_creates_expected_files(tmp_path) -> None:
    """odk docs generate produces CLI reference and schema MDX files."""
    output_dir = tmp_path / "_generated"

    result = runner.invoke(app, ["docs", "generate", "--output", str(output_dir)])

    assert result.exit_code == 0, result.output

    # CLI reference pages
    expected_cli_pages = [
        "init",
        "component",
        "task",
        "spec",
        "verify",
        "memory",
        "change",
        "scaffold",
        "visual",
        "checkpoint",
        "quickdev",
        "status",
    ]
    for page in expected_cli_pages:
        mdx = output_dir / "cli" / f"{page}.mdx"
        assert mdx.exists(), f"Missing CLI page: {mdx}"
        content = mdx.read_text()
        assert content.startswith("---"), f"Missing frontmatter in {page}.mdx"
        assert f"odk {page}" in content

    # Schema reference page
    schemas_mdx = output_dir / "schemas.mdx"
    assert schemas_mdx.exists(), "Missing schemas.mdx"
    content = schemas_mdx.read_text()
    assert "Component Schemas" in content
    # Should contain at least the entity and route schemas
    assert "entity" in content
    assert "route" in content


def test_docs_generate_cli_pages_have_code_blocks(tmp_path) -> None:
    """Generated CLI pages contain help text in code blocks."""
    output_dir = tmp_path / "_generated"
    runner.invoke(app, ["docs", "generate", "--output", str(output_dir)])

    init_mdx = output_dir / "cli" / "init.mdx"
    content = init_mdx.read_text()
    assert "```text" in content
    assert "```" in content


def test_docs_generate_group_pages_have_subcommands(tmp_path) -> None:
    """Group command pages include subcommand sections."""
    output_dir = tmp_path / "_generated"
    result = runner.invoke(app, ["docs", "generate", "--output", str(output_dir)])
    assert result.exit_code == 0, result.output

    component_mdx = output_dir / "cli" / "component.mdx"
    content = component_mdx.read_text()
    # component has subcommands — each rendered as ## `odk component <sub>`
    # Match any subcommand heading (e.g. list, show, validate)
    import re

    subcommand_headings = re.findall(r"^## `odk component \w+`", content, re.MULTILINE)
    assert len(subcommand_headings) >= 1, (
        f"Expected at least one subcommand heading in component.mdx, found none. Content preview:\n{content[:500]}"
    )


def test_docs_generate_schemas_contain_yaml(tmp_path) -> None:
    """Schema page contains YAML code blocks from schema files."""
    output_dir = tmp_path / "_generated"
    runner.invoke(app, ["docs", "generate", "--output", str(output_dir)])

    schemas_mdx = output_dir / "schemas.mdx"
    content = schemas_mdx.read_text()
    assert "```yaml" in content


def test_docs_generate_output_count(tmp_path) -> None:
    """Generate reports the correct number of files."""
    output_dir = tmp_path / "_generated"
    result = runner.invoke(app, ["docs", "generate", "--output", str(output_dir)])
    assert "13 files generated" in result.output

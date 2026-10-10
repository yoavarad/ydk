"""ydk docs — documentation generation commands."""

from __future__ import annotations

import json
import re
from pathlib import Path

import typer
import yaml

docs_app = typer.Typer(name="docs", help="Documentation generation")

_SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


def _discover_cli_pages() -> dict[str, dict[str, str]]:
    """Derive the CLI page list from the live Typer app.

    Every visible top-level command except ``docs`` gets a page. Click groups
    are ``group`` pages (with per-subcommand sections); others are ``standalone``.
    """
    import click
    import typer.main

    from ydk.cli import app

    root = typer.main.get_command(app)
    commands = root.commands if isinstance(root, click.Group) else {}
    return {
        name: {"kind": "group" if isinstance(cmd, click.Group) else "standalone"}
        for name, cmd in sorted(commands.items())
        if not cmd.hidden and name != "docs"
    }


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _run_help(args: list[str]) -> str:
    """Run ``ydk <args> --help`` in-process via Typer and return the output.

    ANSI escape codes are stripped so that downstream parsing (e.g.
    ``_extract_subcommands``) works identically regardless of terminal
    capabilities or ``NO_COLOR`` settings.
    """
    from typer.testing import CliRunner

    from ydk.cli import app

    runner = CliRunner()
    result = runner.invoke(app, [*args, "--help"])
    return _ANSI_RE.sub("", result.output)


def _generate_cli_page(slug: str, info: dict[str, str], output_dir: Path) -> Path:
    """Generate a single CLI reference MDX page."""
    title = f"ydk {slug}"
    dest = output_dir / "cli" / f"{slug}.mdx"
    dest.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "---",
        f'title: "{title}"',
        f'description: "CLI reference for ydk {slug}"',
        "---",
        "",
        f"# `ydk {slug}`",
        "",
    ]

    # Main help text
    main_help = _run_help([slug])
    lines.extend(
        [
            "```text",
            main_help.rstrip(),
            "```",
            "",
        ]
    )

    # For group commands, also capture each subcommand
    if info["kind"] == "group":
        subcommands = _extract_subcommands(main_help)
        for sub in subcommands:
            sub_help = _run_help([slug, sub])
            lines.extend(
                [
                    f"## `ydk {slug} {sub}`",
                    "",
                    "```text",
                    sub_help.rstrip(),
                    "```",
                    "",
                ]
            )

    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def _extract_subcommands(help_text: str) -> list[str]:
    """Parse Typer help output to extract subcommand names.

    Typer with Rich renders commands inside a box like::

        ╭─ Commands ──────────╮
        │ list   Description  │
        │ show   Description  │
        ╰─────────────────────╯

    Rich falls back to square corners (``┌ ┐ └ ┘``) instead of rounded ones
    (``╭ ╮ ╰ ╯``) in some terminal modes (e.g. legacy Windows consoles), so
    both styles must be recognized.
    """
    subcommands: list[str] = []
    in_commands = False
    for line in help_text.splitlines():
        stripped = line.strip()
        # Detect the Commands section header (Rich box style, either corner style)
        if "Commands" in stripped and stripped.startswith(("╭", "┌")):
            in_commands = True
            continue
        if in_commands:
            # End of box
            if stripped.startswith(("╰", "└")):
                break
            # Content rows start with │
            if stripped.startswith("│") and stripped.endswith("│"):
                inner = stripped[1:-1].strip()
                parts = inner.split()
                if parts:
                    candidate = parts[0]
                    # Skip decorative / empty rows
                    if candidate and not candidate.startswith("─"):
                        subcommands.append(candidate)
    return subcommands


def _generate_schemas_page(output_dir: Path) -> Path:
    """Generate the component schemas reference MDX page."""
    dest = output_dir / "schemas.mdx"
    dest.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "---",
        'title: "Component Schemas"',
        'description: "All built-in component schema definitions"',
        "---",
        "",
        "# Component Schemas",
        "",
        "These schemas define the structure of YDK component manifests.",
        "Each component YAML file in `.ydk/components/` must conform to its schema.",
        "",
    ]

    if not _SCHEMAS_DIR.is_dir():
        lines.append("No schemas directory found.")
        dest.write_text("\n".join(lines), encoding="utf-8")
        return dest

    for schema_file in sorted(_SCHEMAS_DIR.glob("*.yaml")):
        raw = yaml.safe_load(schema_file.read_text(encoding="utf-8"))
        if not raw or not isinstance(raw, dict):
            continue

        name = raw.get("name", schema_file.stem)
        description = raw.get("description", "")
        version = raw.get("version", "?")

        lines.extend(
            [
                f"## `{name}` (v{version})",
                "",
                description,
                "",
                "```yaml",
                schema_file.read_text(encoding="utf-8").rstrip(),
                "```",
                "",
            ]
        )

    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


@docs_app.command("generate")
def generate(
    output: Path = typer.Option(  # noqa: B008
        Path("docs/content/docs/_generated"),
        "--output",
        "-o",
        help="Output directory for generated MDX files",
    ),
) -> None:
    """Generate documentation from live CLI help and schemas."""
    output.mkdir(parents=True, exist_ok=True)

    generated: list[str] = []

    # CLI reference pages
    pages = _discover_cli_pages()
    for slug, info in pages.items():
        path = _generate_cli_page(slug, info, output)
        generated.append(str(path))
        typer.echo(f"  Generated: {path}")

    # Navigation for CLI pages, derived from the same live list
    meta = output / "cli" / "meta.json"
    meta.write_text(
        json.dumps({"title": "CLI Commands", "pages": sorted(pages)}, indent=2) + "\n",
        encoding="utf-8",
    )

    # Schemas page
    path = _generate_schemas_page(output)
    generated.append(str(path))
    typer.echo(f"  Generated: {path}")

    typer.echo(f"\n{len(generated)} files generated in {output}")

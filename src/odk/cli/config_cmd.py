"""odk config — configuration management commands."""

from __future__ import annotations

from pathlib import Path

import typer
import yaml
from pydantic import ValidationError

from odk.cli._helpers import get_output_format
from odk.core.config import get_config_value, load_config, save_config, set_config_value
from odk.output.console import console
from odk.output.formatters import OutputFormat, get_formatter

config_app = typer.Typer(name="config", help="Manage ODK configuration")

CONFIG_PATH = Path(".odk/config.yaml")


@config_app.command()
def show(ctx: typer.Context) -> None:
    """Show current config."""
    config = load_config(CONFIG_PATH)
    fmt = get_output_format(ctx)
    if fmt == OutputFormat.human:
        # Use console.print for human format so Rich markup is rendered
        console.print(get_formatter(fmt).format(config))
    else:
        # JSON/YAML: plain output without Rich markup
        formatter = get_formatter(fmt)
        typer.echo(formatter.format(config))


@config_app.command()
def get(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Dot-separated config key"),
) -> None:
    """Get a config value."""
    if not CONFIG_PATH.is_file():
        typer.echo("Error: no config found. Run 'odk init' first.", err=True)
        raise typer.Exit(code=1)

    raw = yaml.safe_load(CONFIG_PATH.read_text())
    value = get_config_value(raw, key)
    if value is None:
        typer.echo(f"Key not found: {key}", err=True)
        raise typer.Exit(code=1)
    typer.echo(str(value))


@config_app.command("set")
def set_value(
    key: str = typer.Argument(..., help="Dot-separated config key"),
    value: str = typer.Argument(..., help="Value to set"),
) -> None:
    """Set a config value."""
    if not CONFIG_PATH.is_file():
        typer.echo("Error: no config found. Run 'odk init' first.", err=True)
        raise typer.Exit(code=1)

    raw = yaml.safe_load(CONFIG_PATH.read_text())
    try:
        updated = set_config_value(raw, key, value)
    except ValidationError as exc:
        typer.echo(f"Validation error: {exc}", err=True)
        raise typer.Exit(code=1) from None

    save_config(updated, CONFIG_PATH)
    typer.echo(f"{key} = {value}")


@config_app.command()
def validate() -> None:
    """Validate config."""
    if not CONFIG_PATH.is_file():
        typer.echo("Error: no config found. Run 'odk init' first.", err=True)
        raise typer.Exit(code=1)

    try:
        load_config(CONFIG_PATH)
        typer.echo("Config is valid.")
    except (ValidationError, Exception) as exc:
        typer.echo(f"Config invalid: {exc}", err=True)
        raise typer.Exit(code=1) from None

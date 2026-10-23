"""ydk skills — install bundled Claude skills/agents and report version drift."""

from __future__ import annotations

import importlib.metadata

import typer

from ydk.core.skills_sync import bundled_skills_dir, claude_config_dir, skill_status, sync_skills

skills_app = typer.Typer(name="skills", help="Install bundled Claude skills and agents")


@skills_app.command("sync")
def sync(dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be copied")) -> None:
    """Copy bundled skills to <claude-config>/skills and agents to <claude-config>/agents."""
    version = importlib.metadata.version("ydk")
    target = claude_config_dir()
    actions = sync_skills(bundled_skills_dir(), target, version, dry_run=dry_run)
    if not actions:
        typer.echo(f"No bundled skills found in {bundled_skills_dir()}", err=True)
        raise typer.Exit(code=1)
    prefix = "[dry-run] would copy" if dry_run else "copied"
    for action in actions:
        typer.echo(f"{prefix} {action}")
    if not dry_run:
        typer.echo(f"Synced {len(actions)} item(s) to {target} at ydk {version}")


@skills_app.command("status")
def status() -> None:
    """Report each bundled skill's installed version stamp vs the CLI version."""
    version = importlib.metadata.version("ydk")
    typer.echo(f"ydk {version} — skills in {claude_config_dir() / 'skills'}")
    for name, stamp in skill_status(bundled_skills_dir(), claude_config_dir()):
        if stamp is None:
            state = "not installed (or unstamped)"
        elif stamp == version:
            state = f"ok ({stamp})"
        else:
            state = f"drift: installed {stamp}, CLI {version} — run 'ydk skills sync'"
        typer.echo(f"  {name}: {state}")

"""CLI commands for verification checks."""

import asyncio
import time

import typer
import yaml

from ydk.cli._helpers import format_or_echo
from ydk.core.config import load_config
from ydk.core.verifier import Verifier
from ydk.output.console import console

verify_app = typer.Typer(name="verify", help="Run verification checks")


def _make_verifier(*, use_cache: bool = True) -> Verifier:
    """Build a Verifier, respecting the enabled plugin list from config."""
    config = load_config()
    enabled = config.verification.enabled or None
    return Verifier(enabled_plugins=enabled, use_cache=use_cache)


@verify_app.command("run")
def run(
    name: str | None = typer.Option(None, "--name", help="Run only this plugin"),
    trigger: str | None = typer.Option(None, "--trigger", help="Filter by trigger ID (e.g. git:pre-commit)"),
    auto_fix: bool = typer.Option(False, "--auto-fix", help="Auto-fix violations before checking"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass the verification cache"),
    retry: int | None = typer.Option(None, "--retry", help="Retry verification up to N times on failure"),
    repair: bool = typer.Option(False, "--repair", help="Alias for --retry 3"),
    save_proof: bool = typer.Option(False, "--save-proof"),
    task_id: str | None = typer.Option(None, "--task-id"),
    pr: str | None = typer.Option(None, "--pr", help="PR URL — post results as a PR comment"),
    capture: bool = typer.Option(False, "--capture", help="Capture verification output to proof files"),
) -> None:
    """Run verification plugins."""
    # Resolve retry count: --repair is shorthand for --retry 3
    max_retries = retry if retry is not None else (3 if repair else None)

    v = _make_verifier(use_cache=not no_cache)
    context: dict[str, object] = {"project_root": str(v._root.resolve())}

    effective_trigger = trigger or "manual"
    if effective_trigger == "pre-push":
        from ydk.services.git import LocalGitService

        changed_files = LocalGitService(cwd=str(v._root)).changed_files(".", base_ref="main", extension="")
        if changed_files:
            context["changed_files"] = changed_files

    # Retry loop path -- only for full runs (no --name filter)
    if max_retries is not None and name is None:
        from ydk.core.auto_repair import RepairLoop

        loop = RepairLoop()
        result = asyncio.run(loop.run(v, max_retries=max_retries, trigger=effective_trigger, context=context))

        # Display structured errors from each attempt
        for i, errors_json in enumerate(result.errors_per_attempt, 1):
            console.print(f"\n[bold red]Attempt {i}/{max_retries} FAILED[/bold red]")
            console.print("[dim]Structured errors (for coding agent):[/dim]")
            console.print(errors_json)

        if result.final_passed:
            console.print(f"\n[bold green]ALL PASSED[/bold green] after {result.attempts} attempt(s)")
            raise typer.Exit(0)
        else:
            console.print(f"\n[bold red]FAILED[/bold red] after {result.attempts} attempt(s) (max retries reached)")
            raise typer.Exit(1)

    if name:
        start = time.time()
        plugins = v.discover_plugins()
        matched = v.filter_by_name(plugins, name)
        if not matched:
            console.print(f"[red]Plugin not found: {name}[/red]")
            raise typer.Exit(1)
        results_list = asyncio.run(v.run_layer(matched, context, auto_fix=auto_fix))
        report = v._build_report(results_list, start)
    else:
        effective_trigger = trigger or "manual"
        report = asyncio.run(v.run_all(trigger=effective_trigger, context=context, auto_fix=auto_fix))

    # Display auto-fix summary if any plugin reported fix counts
    if auto_fix:
        total_fixed = 0
        total_remaining = 0
        for check in report.checks:
            if check.detail and "auto_fixed_count" in check.detail:
                total_fixed += int(check.detail["auto_fixed_count"])
                total_remaining += int(check.detail["remaining_count"])
        if total_fixed > 0 or total_remaining > 0:
            console.print(
                f"\n[bold yellow]Auto-fixed {total_fixed} issues. "
                f"{total_remaining} issues remain (manual fix required).[/bold yellow]"
            )
            console.print("[yellow]WARNING: Auto-fix modified files. Review changes before committing.[/yellow]")

    # Display results
    console.print("\n[bold]Verification Report[/bold]\n")
    for check in report.checks:
        icon = "[green]✓[/green]" if check.passed else "[red]✗[/red]"
        console.print(f"  {icon} {check.name} ({check.duration_seconds}s)")
        if not check.passed:
            for line in check.output.splitlines()[:5]:
                console.print(f"    {line}")

    if report.all_passed:
        console.print(f"\n[bold green]ALL PASSED[/bold green] ({report.total_duration_seconds}s)")
    else:
        console.print(f"\n[bold red]FAILED[/bold red] ({report.total_duration_seconds}s)")

    if capture:
        from pathlib import Path as _Path

        from ydk.core.proof_capture import ProofCapture

        effective_task_id = task_id or "latest"
        proof_dir = _Path(".ydk") / "proofs" / effective_task_id
        pc = ProofCapture(proof_dir)
        artifacts = pc.save_report(report)
        console.print(f"[dim]Proof files captured to: {proof_dir}[/dim]")
        if artifacts.verification_report_path:
            console.print(f"[dim]  report: {artifacts.verification_report_path}[/dim]")
        for name, path in artifacts.plugin_outputs.items():
            console.print(f"[dim]  {name}: {path}[/dim]")

    if save_proof:
        path = v.save_proof(report, task_id)
        console.print(f"[dim]Proof saved: {path}[/dim]")

    if pr:
        from ydk.core.pr_commenter import PRCommenter

        try:
            PRCommenter().post_verification_results(pr, report)
            console.print(f"[dim]PR comment posted: {pr}[/dim]")
        except RuntimeError as exc:
            console.print(f"[red]Failed to post PR comment: {exc}[/red]")

    raise typer.Exit(0 if report.all_passed else 1)


@verify_app.command("check-guard")
def check_guard(
    trigger: str = typer.Argument(..., help="Guard trigger ID (guard:edit or guard:command)"),
) -> None:
    """Run guard plugins for real-time enforcement. Reads context from stdin."""
    import json
    import sys

    from ydk.core.verifier import Verifier

    # Validate trigger is a guard trigger
    if not trigger.startswith("guard:"):
        sys.stderr.write(f"Invalid guard trigger: {trigger}. Must start with 'guard:'\n")
        raise typer.Exit(1)

    # Read context from stdin — fail OPEN if anything goes wrong
    try:
        raw = sys.stdin.read()
        context = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError, ValueError, UnicodeDecodeError):
        # Fail open — don't block on invalid/missing stdin
        context = {}

    # Build verifier rooted at project_root from context (or cwd)
    from pathlib import Path

    project_root = Path(context.get("project_root", "."))
    v = Verifier(project_root=project_root, use_cache=False)

    passed, message = v.run_guard(trigger, context)

    if not passed:
        sys.stderr.write(message + "\n")
        raise typer.Exit(2)

    raise typer.Exit(0)


@verify_app.command("list")
def list_plugins(ctx: typer.Context) -> None:
    """List all discovered verification plugins."""
    v = _make_verifier()
    plugins = v.discover_plugins()

    if not plugins:
        console.print("[yellow]No verification plugins found.[/yellow]")
        return

    data = [
        {
            "name": p.name,
            "description": p.description,
            "trigger": p.trigger,
            "parallel": p.parallel,
            "timeout": p.timeout,
            "requires": p.requires,
        }
        for p in plugins
    ]
    if format_or_echo(ctx, data):
        return

    console.print("\n[bold]Verification Plugins[/bold]\n")
    for p in plugins:
        console.print(f"  [cyan]{p.name}[/cyan] ({p.trigger})")
        console.print(f"    {p.description}")
        console.print(f"    parallel: {p.parallel}  timeout: {p.timeout}s")
        console.print(f"    requires: {', '.join(p.requires)}")


@verify_app.command("create")
def create_plugin(
    name: str = typer.Argument(..., help="Plugin name"),
    trigger: str = typer.Option("git:pre-commit", "--trigger", help="Trigger ID (e.g. git:pre-commit)"),
) -> None:
    """Create a new project-specific verification plugin."""
    from pathlib import Path

    plugin_dir = Path(".ydk") / "verifications" / name
    if plugin_dir.exists():
        console.print(f"[red]Plugin already exists: {plugin_dir}[/red]")
        raise typer.Exit(1)

    plugin_dir.mkdir(parents=True)

    manifest = {
        "name": name,
        "description": f"Custom verification: {name}",
        "trigger": trigger,
        "parallel": True,
        "timeout": 30,
        "requires": [],
    }
    (plugin_dir / "manifest.yaml").write_text(yaml.dump(manifest, default_flow_style=False))

    check_template = f'''#!/usr/bin/env python3
"""Verification plugin: {name}."""

import json
import sys
import time


def main() -> None:
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    # TODO: implement your check here
    passed = True
    output = "Check not yet implemented"

    result = {{
        "name": "{name}",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": None,
    }}
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
'''

    (plugin_dir / "check.py").write_text(check_template)
    console.print(f"[green]Created plugin at {plugin_dir}[/green]")
    console.print(f"  Edit {plugin_dir / 'check.py'} to implement your check.")


@verify_app.command("clear-cache")
def clear_cache(
    plugin_name: str | None = typer.Option(None, "--plugin", help="Clear cache for a specific plugin only"),
) -> None:
    """Clear the verification result cache."""
    v = _make_verifier()
    v.cache.invalidate(plugin_name)
    if plugin_name:
        console.print(f"[green]Cache cleared for plugin: {plugin_name}[/green]")
    else:
        console.print("[green]All verification caches cleared.[/green]")

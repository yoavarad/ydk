"""ydk doctor — check YDK environment health."""

from __future__ import annotations

import typer

from ydk.core.doctor import CheckSeverity, Doctor
from ydk.output.console import console


def doctor_command() -> None:
    """Check YDK environment health."""
    doc = Doctor()
    results = doc.run_all()

    console.print("\nYDK Doctor — checking environment...\n")

    for r in results:
        icon = {
            CheckSeverity.ok: "[green]✓[/green]",
            CheckSeverity.warning: "[yellow]⚠[/yellow]",
            CheckSeverity.error: "[red]✗[/red]",
        }
        console.print(f"  {icon[r.severity]} {r.name}: {r.message}")
        if r.detail:
            console.print(f"    → {r.detail}")

    ok_count = sum(1 for r in results if r.severity == CheckSeverity.ok)
    warns = sum(1 for r in results if r.severity == CheckSeverity.warning)
    errs = sum(1 for r in results if r.severity == CheckSeverity.error)
    total = len(results)

    summary_parts = [f"\n{ok_count}/{total} passed."]
    if warns:
        summary_parts.append(f" {warns} warning(s).")
    if errs:
        summary_parts.append(f" {errs} error(s).")
    console.print("".join(summary_parts))

    raise typer.Exit(code=1 if errs else 0)

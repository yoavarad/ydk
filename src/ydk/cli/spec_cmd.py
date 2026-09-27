"""ydk spec -- spec management and quality checks."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ydk.core.component_checker import ComponentChecker
from ydk.core.component_linker import ComponentLinker
from ydk.core.component_registry import ComponentRegistry
from ydk.core.config import load_config
from ydk.core.reviewer import (
    ReviewResult,
    load_all_reviewers,
    run_reviewer,
)
from ydk.models.component import LinkerResult, ScannerResult
from ydk.models.evaluation import (
    ComponentFinding,
    CriterionResult,
    SpecVerificationReport,
)
from ydk.output.console import console
from ydk.services.git import LocalGitService

spec_app = typer.Typer(name="spec", help="Spec management and quality checks")


def _reviewer_results_to_criterion_results(
    results: list[ReviewResult],
    threshold_map: dict[str, int],
) -> list[CriterionResult]:
    """Convert ReviewResult objects to CriterionResult for report compatibility."""
    criterion_results: list[CriterionResult] = []
    for r in results:
        threshold = threshold_map.get(r.reviewer_id, 8)
        criterion_results.append(
            CriterionResult(
                criterion_id=r.reviewer_id,
                score=float(r.score),
                passed=r.score >= threshold,
                reasoning=r.reasoning,
                suggestions=r.suggestions,
            )
        )
    return criterion_results


def _run_reviewer_agents(
    spec_content: str,
    config: object,
    rubric_filter: str | None = None,
    verbose: bool = False,
) -> tuple[list[ReviewResult], dict[str, list[dict[str, object]]]]:
    """Run the deterministic reviewer tools against spec content.

    YDK makes no external LLM calls (#231): only reviewers that define
    deterministic tools run; the rest are judged by the in-session agent.

    Returns:
        A tuple of (review results, deterministic findings per reviewer ID).
    """
    from ydk.models.config import YdkConfig

    assert isinstance(config, YdkConfig)

    # Build threshold overrides from config
    threshold_overrides: dict[str, int] = {
        "completeness": config.spec_check.thresholds.completeness,
        "clarity": config.spec_check.thresholds.clarity,
        "quality": config.spec_check.thresholds.quality,
    }

    # Resolve reviewers directory — project-level first, then built-in
    reviewers_dir = Path(config.spec_check.reviewers_path)
    if not reviewers_dir.is_dir():
        from ydk.spec_reviewers import REVIEWERS_DIR

        reviewers_dir = REVIEWERS_DIR

    reviewers = load_all_reviewers(reviewers_dir, threshold_overrides=threshold_overrides)

    # Also load custom reviewers from .ydk/spec-reviewers/custom/ if present
    custom_dir = Path(config.spec_check.reviewers_path) / "custom"
    if custom_dir.is_dir() and any(custom_dir.glob("*.yaml")):
        reviewers.extend(load_all_reviewers(custom_dir, threshold_overrides=threshold_overrides))

    # Apply rubric filter; keep only reviewers with deterministic tools
    if rubric_filter is not None:
        reviewers = [r for r in reviewers if r.group == rubric_filter]
    reviewers = [r for r in reviewers if r.tools]

    if not reviewers:
        return [], {}

    if verbose:
        for r in reviewers:
            tool_names = [getattr(t, "__name__", str(t)) for t in r.tools]
            typer.echo(
                f"  [{r.id}] {r.group}/{r.name} (threshold={r.threshold}, tier={r.model_tier}) tools={tool_names}"
            )

    results = sorted((run_reviewer(r, spec_content) for r in reviewers), key=lambda r: r.reviewer_id)
    deterministic_findings = {r.reviewer_id: r.findings for r in results if r.findings}
    return results, deterministic_findings


def _run_component_checks(config: object) -> list[ComponentFinding]:
    """Run deterministic component quality checks."""
    from ydk.models.config import YdkConfig

    assert isinstance(config, YdkConfig)
    components_dir = Path(config.components.components_path)
    schemas_dir = Path(config.components.schemas_path)
    checker = ComponentChecker()
    return checker.check_all(components_dir, schemas_dir)


def _run_linker_checks(config: object) -> LinkerResult:
    """Run Layer A deterministic reference linker."""
    from ydk.models.config import YdkConfig

    assert isinstance(config, YdkConfig)
    schemas_dir = Path(config.components.schemas_path)
    components_dir = Path(config.components.components_path)
    narratives_dir = Path(config.project.spec_location)
    registry = ComponentRegistry(schemas_dir=schemas_dir, components_dir=components_dir)
    linker = ComponentLinker(registry=registry, narratives_dir=narratives_dir)
    return linker.validate_references()


def _format_component_checks(findings: list[ComponentFinding]) -> list[str]:
    """Format component check findings for human-readable output."""
    lines: list[str] = []

    if not findings:
        lines.append("  [green]OK[/green] All component checks passed")
        return lines

    for f in findings:
        icon = "[red]FAIL[/red]" if f.severity == "error" else "[yellow]WARN[/yellow]"
        lines.append(f"  {icon} {f.check}: {f.component_id}")
        lines.append(f"     File: {f.file_path}")
        lines.append(f"     -> {f.message}")
        lines.append(f"     -> {f.suggestion}")
        lines.append("")

    return lines


def _format_linker_result(result: LinkerResult) -> list[str]:
    """Format linker result for human-readable output."""
    lines: list[str] = []

    valid_count = len(result.valid_refs)
    if result.undefined_refs:
        lines.append(f"  [red]FAIL[/red] {len(result.undefined_refs)} undefined reference(s):")
        lines.extend(f"     - {ref}" for ref in result.undefined_refs)
        lines.append("     -> Define these components or fix the references.")
        lines.append("")

    if result.orphaned_components:
        lines.append(f"  [yellow]WARN[/yellow] {len(result.orphaned_components)} orphaned component(s):")
        lines.extend(f"     - {comp}" for comp in result.orphaned_components)
        lines.append("     -> Either reference these in a narrative or remove them.")
        lines.append("")

    if result.broken_cross_refs:
        lines.append(f"  [red]FAIL[/red] {len(result.broken_cross_refs)} broken cross-reference(s):")
        lines.extend(f"     - {ref}" for ref in result.broken_cross_refs)
        lines.append("")

    if not result.undefined_refs and not result.broken_cross_refs:
        lines.append(f"  [green]OK[/green] {valid_count} references in narratives — all resolve")

    if result.orphaned_components:
        lines.append(
            f"  [yellow]WARN[/yellow] {len(result.orphaned_components)} orphaned components "
            "(defined but never referenced)"
        )

    return lines


def _format_reviewer_results(results: list[ReviewResult]) -> list[str]:
    """Format reviewer agent results for human-readable output."""
    lines: list[str] = []
    for r in results:
        icon = "[green]OK[/green]" if r.passed else "[red]FAIL[/red]"
        timing = f" ({r.elapsed_seconds:.1f}s)" if r.elapsed_seconds > 0 else ""
        lines.append(f"  {icon} [{r.reviewer_id}] {r.name}: {r.score}/10{timing}")
        if r.reasoning:
            lines.append(f"     {r.reasoning[:120]}")
        lines.extend(f"     -> {s}" for s in r.suggestions)
        if r.findings:
            finding_count = len(r.findings)
            lines.append(f"     ({finding_count} finding{'s' if finding_count != 1 else ''} from tools)")
    return lines


def _build_report(
    component_findings: list[ComponentFinding],
    linker_result: LinkerResult,
    narrative_scores: list[CriterionResult],
    scanner_result: ScannerResult,
) -> SpecVerificationReport:
    """Assemble all results into a combined report."""
    errors = sum(1 for f in component_findings if f.severity == "error")
    errors += len(linker_result.undefined_refs)
    errors += len(linker_result.broken_cross_refs)
    errors += sum(1 for s in narrative_scores if not s.passed)

    errors += len(linker_result.orphaned_components)

    warnings = sum(1 for f in component_findings if f.severity == "warning")
    warnings += len(scanner_result.unlinked_mentions)

    passed = errors == 0
    summary = f"{errors} error{'s' if errors != 1 else ''}, {warnings} warning{'s' if warnings != 1 else ''}"

    return SpecVerificationReport(
        component_findings=component_findings,
        linker_result=linker_result,
        narrative_scores=narrative_scores,
        scanner_result=scanner_result,
        passed=passed,
        summary=summary,
    )


def _format_report_human(
    report: SpecVerificationReport,
    reviewer_results: list[ReviewResult] | None = None,
) -> str:
    """Format the full verification report for human consumption (legacy)."""
    lines: list[str] = []
    lines.append("")
    lines.append("[bold]" + "=" * 47 + "[/bold]")
    lines.append("[bold] YDK Spec Verification Report[/bold]")
    lines.append("[bold]" + "=" * 47 + "[/bold]")
    lines.append("")

    # Component checks
    lines.append("[bold]-- Component Checks (deterministic) --[/bold]")
    lines.append("")
    lines.extend(_format_component_checks(report.component_findings))
    lines.append("")

    # Reference integrity
    lines.append("[bold]-- Reference Integrity --[/bold]")
    lines.append("")
    lines.extend(_format_linker_result(report.linker_result))
    lines.append("")

    # Narrative quality — use reviewer results if available
    if reviewer_results:
        lines.append("[bold]-- Narrative Quality (Reviewer Agents) --[/bold]")
        lines.append("")
        lines.extend(_format_reviewer_results(reviewer_results))
        lines.append("")
    elif report.narrative_scores:
        lines.append("[bold]-- Narrative Quality (LLM-evaluated) --[/bold]")
        lines.append("")
        for score in report.narrative_scores:
            icon = "[green]OK[/green]" if score.passed else "[red]FAIL[/red]"
            lines.append(f"  {icon} {score.criterion_id}: {score.reasoning[:80]}")
            lines.extend(f"     -> {s}" for s in score.suggestions)
        lines.append("")

    # Unlinked concepts
    if report.scanner_result.unlinked_mentions:
        lines.append("[bold]-- Unlinked Concepts (LLM scan) --[/bold]")
        lines.append("")
        lines.append(
            f"  [yellow]WARN[/yellow] {len(report.scanner_result.unlinked_mentions)} "
            "concepts mentioned without [ydk:...] references:"
        )
        lines.extend(
            f'     Line {finding.line}: "{finding.text}" -> {finding.suggested_id}'
            for finding in report.scanner_result.unlinked_mentions
        )
        lines.append("")

    # Summary
    lines.append("[bold]" + "=" * 47 + "[/bold]")
    status = "[bold green]PASSED[/bold green]" if report.passed else "[bold red]NEEDS WORK[/bold red]"
    lines.append(f" Result: {report.summary} — {status}")
    lines.append("[bold]" + "=" * 47 + "[/bold]")

    return "\n".join(lines)


def _score_color(score: int) -> str:
    """Return Rich color name for a numeric score."""
    if score <= 3:
        return "red"
    if score <= 6:
        return "yellow"
    return "green"


def _build_deterministic_tool_map(
    reviewer_results: list[ReviewResult],
    deterministic_findings: dict[str, list[dict[str, object]]],
) -> dict[str, dict[str, list[dict[str, object]]]]:
    """Group deterministic findings by reviewer ID and tool name.

    Returns:
        {reviewer_id: {tool_name: [finding, ...]}}
    """
    result: dict[str, dict[str, list[dict[str, object]]]] = {}
    for reviewer_id, findings in deterministic_findings.items():
        tool_groups: dict[str, list[dict[str, object]]] = {}
        for f in findings:
            tool_name = str(f.get("tool", f.get("category", "scan")))
            tool_groups.setdefault(tool_name, []).append(f)
        result[reviewer_id] = tool_groups
    return result


def _format_structured_report(
    report: SpecVerificationReport,
    reviewer_results: list[ReviewResult],
    deterministic_findings: dict[str, list[dict[str, object]]],
    duration_seconds: float,
    project_name: str,
    file_count: int,
    component_count: int,
) -> None:
    """Print the structured report with Rich colors and dump to file."""
    separator = "=" * 63

    # -- Tally pass/fail/deterministic --
    failed = sum(1 for r in reviewer_results if not r.passed)
    passed = sum(1 for r in reviewer_results if r.passed and not deterministic_findings.get(r.reviewer_id))
    det_passed = sum(1 for r in reviewer_results if r.passed and deterministic_findings.get(r.reviewer_id))

    comp_check_total = component_count
    comp_check_ok = comp_check_total - sum(1 for f in report.component_findings if f.severity == "error")
    ref_total = len(report.linker_result.valid_refs) + len(report.linker_result.undefined_refs)
    ref_ok = len(report.linker_result.valid_refs)

    # -- Header --
    console.print(f"\n{separator}")
    console.print(" [bold]YDK Spec Verification Report[/bold]")
    console.print(
        f" Project: {project_name} | Files: {file_count}"
        f" | Components: {component_count} | Duration: {duration_seconds:.0f}s"
    )
    console.print(separator)

    # -- Summary table --
    console.print("\n[bold]-- Summary --[/bold]\n")

    summary_table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    summary_table.add_column("Criterion", width=30)
    summary_table.add_column("Score", justify="right", width=6)
    summary_table.add_column("Threshold", justify="right", width=10)
    summary_table.add_column("Status", width=6)
    summary_table.add_column("Time", justify="right", width=8)

    for r in reviewer_results:
        sc = _score_color(r.score)
        status_color = "green" if r.passed else "red"
        status_text = "PASS" if r.passed else "FAIL"
        elapsed = f"{r.elapsed_seconds:.1f}s" if r.elapsed_seconds > 0 else ""
        summary_table.add_row(
            f"[bold]{r.reviewer_id} {r.name}[/bold]",
            f"[{sc}]{r.score}[/{sc}]",
            "8",
            f"[{status_color}]{status_text}[/{status_color}]",
            elapsed,
        )

    # Deterministic rows
    comp_status = "PASS" if comp_check_ok == comp_check_total else "FAIL"
    comp_color = "green" if comp_status == "PASS" else "red"
    summary_table.add_row(
        "[bold]Component Checks[/bold]",
        "",
        f"{comp_check_ok}/{comp_check_total}",
        f"[{comp_color}]{comp_status}[/{comp_color}]",
        "",
    )

    ref_status = "PASS" if ref_ok == ref_total and not report.linker_result.undefined_refs else "FAIL"
    ref_color = "green" if ref_status == "PASS" else "red"
    summary_table.add_row(
        "[bold]Reference Integrity[/bold]",
        "",
        f"{ref_ok}/{ref_total}" if ref_total > 0 else "0/0",
        f"[{ref_color}]{ref_status}[/{ref_color}]",
        "",
    )

    console.print(summary_table)

    # -- Summary result line --
    console.print(f"\n RESULT: {failed} failed, {passed} passed, {det_passed} deterministic passed\n")

    # -- Deterministic Tool Findings table --
    total_det_findings = sum(len(fl) for fl in deterministic_findings.values())
    if total_det_findings > 0:
        console.print("[bold]-- Deterministic Tool Findings --[/bold]\n")
        tool_map = _build_deterministic_tool_map(reviewer_results, deterministic_findings)

        det_table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        det_table.add_column("Reviewer", width=10)
        det_table.add_column("Tool", width=30)
        det_table.add_column("Findings", justify="right", width=10)

        for rev_id, tool_groups in sorted(tool_map.items()):
            first = True
            for tool_name, tool_findings in sorted(tool_groups.items()):
                det_table.add_row(
                    rev_id if first else "",
                    tool_name,
                    str(len(tool_findings)),
                )
                first = False

        console.print(det_table)
        console.print(f"\n Total deterministic findings: {total_det_findings}\n")

    # -- Per-criterion detail sections --
    for r in reviewer_results:
        sc = _score_color(r.score)
        status_text = "FAIL" if not r.passed else "PASS"
        console.print(f"[bold]-- {r.reviewer_id} {r.name} -- [{sc}]{r.score}/10[/{sc}] {status_text} --[/bold]\n")

        if r.reasoning:
            console.print(" LLM Assessment:")
            for line in r.reasoning.split("\n"):
                console.print(f"   {line}")
            console.print()

        if r.suggestions:
            console.print(" Suggestions:")
            for i, s in enumerate(r.suggestions, 1):
                console.print(f"   {i}. {s}")
            console.print()

        if r.findings:
            console.print(f" Tool Findings ({len(r.findings)}):")
            for f in r.findings:
                line_num = f.get("line", "?")
                text = f.get("text", "")
                msg = f.get("message", "")
                display = f"{text} -- {msg}" if msg else str(text)
                console.print(f"   [dim]Line {line_num}:[/dim] {display}")
            console.print()

    # -- Footer --
    console.print(separator)
    console.print(
        f" {failed} failed | {passed} passed | {det_passed} deterministic passed | {duration_seconds:.0f}s total"
    )
    console.print(separator)
    console.print()


def _dump_report_files(
    report: SpecVerificationReport,
    reviewer_results: list[ReviewResult],
    deterministic_findings: dict[str, list[dict[str, object]]],
    duration_seconds: float,
    project_name: str,
    file_count: int,
    component_count: int,
    *,
    quiet: bool = False,
) -> Path:
    """Write plain-text and JSON report files to .ydk/reports/.

    Args:
        quiet: If True, suppress console messages about written files.

    Returns:
        The directory where reports were written.
    """
    reports_dir = Path(".ydk/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")

    # -- Plain text dump (no ANSI) --
    txt_path = reports_dir / f"spec-verify-{timestamp}.txt"
    file_console = Console(file=open(str(txt_path), "w", encoding="utf-8"), force_terminal=False, width=120)  # noqa: SIM115

    separator = "=" * 63

    failed = sum(1 for r in reviewer_results if not r.passed)
    passed_count = sum(1 for r in reviewer_results if r.passed and not deterministic_findings.get(r.reviewer_id))
    det_passed = sum(1 for r in reviewer_results if r.passed and deterministic_findings.get(r.reviewer_id))

    comp_check_total = component_count
    comp_check_ok = comp_check_total - sum(1 for f in report.component_findings if f.severity == "error")
    ref_total = len(report.linker_result.valid_refs) + len(report.linker_result.undefined_refs)
    ref_ok = len(report.linker_result.valid_refs)

    file_console.print(separator)
    file_console.print(" YDK Spec Verification Report")
    file_console.print(
        f" Project: {project_name} | Files: {file_count}"
        f" | Components: {component_count} | Duration: {duration_seconds:.0f}s"
    )
    file_console.print(separator)
    file_console.print("\n-- Summary --\n")

    summary_table = Table(show_header=True, box=None, padding=(0, 2))
    summary_table.add_column("Criterion", width=30)
    summary_table.add_column("Score", justify="right", width=6)
    summary_table.add_column("Threshold", justify="right", width=10)
    summary_table.add_column("Status", width=6)
    summary_table.add_column("Time", justify="right", width=8)

    for r in reviewer_results:
        status_text = "PASS" if r.passed else "FAIL"
        elapsed = f"{r.elapsed_seconds:.1f}s" if r.elapsed_seconds > 0 else ""
        summary_table.add_row(f"{r.reviewer_id} {r.name}", str(r.score), "8", status_text, elapsed)

    comp_status = "PASS" if comp_check_ok == comp_check_total else "FAIL"
    summary_table.add_row("Component Checks", "", f"{comp_check_ok}/{comp_check_total}", comp_status, "")
    ref_status = "PASS" if ref_ok == ref_total and not report.linker_result.undefined_refs else "FAIL"
    summary_table.add_row(
        "Reference Integrity",
        "",
        f"{ref_ok}/{ref_total}" if ref_total > 0 else "0/0",
        ref_status,
        "",
    )
    file_console.print(summary_table)
    file_console.print(f"\n RESULT: {failed} failed, {passed_count} passed, {det_passed} deterministic passed\n")

    # Deterministic tool findings
    total_det_findings = sum(len(fl) for fl in deterministic_findings.values())
    if total_det_findings > 0:
        file_console.print("-- Deterministic Tool Findings --\n")
        tool_map = _build_deterministic_tool_map(reviewer_results, deterministic_findings)
        det_table = Table(show_header=True, box=None, padding=(0, 2))
        det_table.add_column("Reviewer", width=10)
        det_table.add_column("Tool", width=30)
        det_table.add_column("Findings", justify="right", width=10)
        for rev_id, tool_groups in sorted(tool_map.items()):
            first = True
            for tool_name, tool_findings in sorted(tool_groups.items()):
                det_table.add_row(rev_id if first else "", tool_name, str(len(tool_findings)))
                first = False
        file_console.print(det_table)
        file_console.print(f"\n Total deterministic findings: {total_det_findings}\n")

    # Per-criterion details
    for r in reviewer_results:
        status_text = "FAIL" if not r.passed else "PASS"
        file_console.print(f"-- {r.reviewer_id} {r.name} -- {r.score}/10 {status_text} --\n")

        if r.reasoning:
            file_console.print(" LLM Assessment:")
            for line in r.reasoning.split("\n"):
                file_console.print(f"   {line}")
            file_console.print()

        if r.suggestions:
            file_console.print(" Suggestions:")
            for i, s in enumerate(r.suggestions, 1):
                file_console.print(f"   {i}. {s}")
            file_console.print()

        if r.findings:
            file_console.print(f" Tool Findings ({len(r.findings)}):")
            for f in r.findings:
                line_num = f.get("line", "?")
                text = f.get("text", "")
                msg = f.get("message", "")
                display = f"{text} -- {msg}" if msg else str(text)
                file_console.print(f"   Line {line_num}: {display}")
            file_console.print()

    file_console.print(separator)
    file_console.print(
        f" {failed} failed | {passed_count} passed | {det_passed} deterministic passed | {duration_seconds:.0f}s total"
    )
    file_console.print(separator)

    # Close the file handle
    if file_console.file and hasattr(file_console.file, "close"):
        file_console.file.close()

    # -- JSON dump --
    json_path = reports_dir / f"spec-verify-{timestamp}.json"
    json_data: dict[str, object] = {
        "project": project_name,
        "timestamp": timestamp,
        "duration_seconds": round(duration_seconds, 1),
        "file_count": file_count,
        "component_count": component_count,
        "passed": report.passed,
        "summary": {
            "failed": failed,
            "passed": passed_count,
            "deterministic_passed": det_passed,
        },
        "reviewers": [
            {
                "reviewer_id": r.reviewer_id,
                "name": r.name,
                "score": r.score,
                "threshold": 8,
                "passed": r.passed,
                "elapsed_seconds": round(r.elapsed_seconds, 1),
                "reasoning": r.reasoning,
                "suggestions": r.suggestions,
                "findings": r.findings,
            }
            for r in reviewer_results
        ],
        "deterministic_findings": {rid: findings for rid, findings in deterministic_findings.items()},
        "component_checks": {
            "total": comp_check_total,
            "passed": comp_check_ok,
            "findings": [f.model_dump() for f in report.component_findings],
        },
        "reference_integrity": {
            "valid_refs": len(report.linker_result.valid_refs),
            "undefined": len(report.linker_result.undefined_refs),
            "orphaned": len(report.linker_result.orphaned_components),
            "broken_cross_refs": len(report.linker_result.broken_cross_refs),
        },
    }
    json_path.write_text(json.dumps(json_data, indent=2, default=str), encoding="utf-8")

    # Also write to the configured results_path for the ignition gate
    try:
        from ydk.core.config import load_config as _lc

        cfg = _lc()
        results_path = Path(cfg.spec_check.results_path)
        results_path.parent.mkdir(parents=True, exist_ok=True)
        results_path.write_text(json.dumps(json_data, indent=2, default=str), encoding="utf-8")
    except Exception:
        # Fallback: write to default location
        default_results = Path(".ydk/spec-check-results.json")
        default_results.parent.mkdir(parents=True, exist_ok=True)
        default_results.write_text(json.dumps(json_data, indent=2, default=str), encoding="utf-8")

    if not quiet:
        console.print(f" Reports written to {reports_dir}/")
        console.print(f"   {txt_path.name}")
        console.print(f"   {json_path.name}\n")

    return reports_dir


def _format_report_json(report: SpecVerificationReport) -> str:
    """Format the full verification report as JSON for agent consumption."""
    component_errors = [f for f in report.component_findings if f.severity == "error"]
    component_warnings = [f for f in report.component_findings if f.severity == "warning"]

    output = {
        "passed": report.passed,
        "component_checks": {
            "passed": len(report.component_findings) == 0,
            "error_count": len(component_errors),
            "warning_count": len(component_warnings),
            "findings": [f.model_dump() for f in report.component_findings],
        },
        "reference_integrity": {
            "valid_refs": len(report.linker_result.valid_refs),
            "orphaned": len(report.linker_result.orphaned_components),
            "undefined": len(report.linker_result.undefined_refs),
            "broken_cross_refs": len(report.linker_result.broken_cross_refs),
        },
        "narrative_criteria": {
            "scores": [s.model_dump() for s in report.narrative_scores],
            "failed": [s.criterion_id for s in report.narrative_scores if not s.passed],
        },
        "unlinked_concepts": {
            "count": len(report.scanner_result.unlinked_mentions),
            "findings": [m.model_dump() for m in report.scanner_result.unlinked_mentions],
        },
        "summary": report.summary,
    }
    return json.dumps(output, indent=2)


@spec_app.command("verify")
def verify(
    rubric: str | None = typer.Option(None, "--rubric", "-r", help="Run specific rubric"),
    all_files: bool = typer.Option(False, "--all-files", help="Check all spec files"),
    base_ref: str = typer.Option("main", "--base-ref", help="Git ref to diff against"),
    output_format: str = typer.Option("human", "--format", "-f", help="Output format: human or json"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run unified quality verification: components, references, and deterministic reviewer tools."""
    start_time = time.monotonic()
    config = load_config()
    git = LocalGitService()

    # Phase 1: Component quality checks (deterministic)
    component_findings = _run_component_checks(config)

    # Phase 2: Reference integrity (deterministic)
    linker_result = _run_linker_checks(config)

    # Phase 3: Narrative quality checks (deterministic reviewer tools)
    narrative_scores: list[CriterionResult] = []
    reviewer_results: list[ReviewResult] = []
    deterministic_findings: dict[str, list[dict[str, object]]] = {}
    if all_files:
        spec_files = git.all_files(config.project.spec_location, extension=".md")
    else:
        spec_files = git.changed_files(config.project.spec_location, base_ref=base_ref, extension=".md")

    if not spec_files and not all_files:
        console.print("[yellow]No changed spec files found.[/yellow]")
        console.print("Use --all-files to verify all specs, or make changes to spec files.")
        raise typer.Exit(code=1)

    if spec_files:
        if verbose:
            typer.echo(f"Files: {', '.join(spec_files)}")

        spec_content = git.read_content(spec_files)

        try:
            reviewer_results, deterministic_findings = _run_reviewer_agents(
                spec_content=spec_content,
                config=config,
                rubric_filter=rubric,
                verbose=verbose,
            )
        except Exception as exc:
            if verbose:
                console.print(f"[yellow]Reviewer agents failed:[/yellow] {exc}")
            reviewer_results = []
            deterministic_findings = {}

        if reviewer_results:
            # Build threshold map from reviewer configs
            threshold_map = {r.reviewer_id: 8 for r in reviewer_results}
            # Apply config overrides via YAML-loaded reviewers
            group_thresholds: dict[str, int] = {
                "completeness": config.spec_check.thresholds.completeness,
                "clarity": config.spec_check.thresholds.clarity,
                "quality": config.spec_check.thresholds.quality,
            }
            reviewers_dir = Path(config.spec_check.reviewers_path)
            if not reviewers_dir.is_dir():
                from ydk.spec_reviewers import REVIEWERS_DIR

                reviewers_dir = REVIEWERS_DIR
            loaded_reviewers = load_all_reviewers(reviewers_dir, threshold_overrides=group_thresholds)
            for lr in loaded_reviewers:
                threshold_map[lr.id] = lr.threshold

            narrative_scores = _reviewer_results_to_criterion_results(reviewer_results, threshold_map)

    # Phase 4: Scanner result (reviewer agents subsume this)
    scanner_result = ScannerResult(unlinked_mentions=[], suggested_ids=[])

    # Build combined report
    report = _build_report(component_findings, linker_result, narrative_scores, scanner_result)
    duration = time.monotonic() - start_time

    # Derive project metadata
    project_name = config.project.name if hasattr(config.project, "name") else Path.cwd().name
    file_count = len(spec_files) if spec_files else 0
    component_count = len(linker_result.valid_refs) + len(linker_result.undefined_refs)

    if output_format == "json":
        typer.echo(_format_report_json(report))
    else:
        _format_structured_report(
            report=report,
            reviewer_results=reviewer_results,
            deterministic_findings=deterministic_findings,
            duration_seconds=duration,
            project_name=project_name,
            file_count=file_count,
            component_count=component_count,
        )

    # Dump report files (suppress console messages when using json output)
    _dump_report_files(
        report=report,
        reviewer_results=reviewer_results,
        deterministic_findings=deterministic_findings,
        duration_seconds=duration,
        project_name=project_name,
        file_count=file_count,
        component_count=component_count,
        quiet=output_format == "json",
    )

    if not report.passed:
        raise typer.Exit(1)


@spec_app.command("list-criteria")
def list_criteria() -> None:
    """List the reviewer criteria with thresholds."""
    config = load_config()

    # Resolve reviewers directory — project-level first, then built-in
    reviewers_dir = Path(config.spec_check.reviewers_path)
    if not reviewers_dir.is_dir():
        from ydk.spec_reviewers import REVIEWERS_DIR

        reviewers_dir = REVIEWERS_DIR

    threshold_overrides: dict[str, int] = {
        "completeness": config.spec_check.thresholds.completeness,
        "clarity": config.spec_check.thresholds.clarity,
        "quality": config.spec_check.thresholds.quality,
    }
    reviewers = load_all_reviewers(reviewers_dir, threshold_overrides=threshold_overrides)

    grouped: dict[str, list[str]] = defaultdict(list)
    for r in reviewers:
        tool_count = len(r.tools)
        grouped[r.group].append(f"[{r.id}] {r.name} (threshold={r.threshold}, tools={tool_count})")

    for group, items in sorted(grouped.items()):
        typer.echo(f"\n{group}:")
        for item in items:
            typer.echo(f"  {item}")

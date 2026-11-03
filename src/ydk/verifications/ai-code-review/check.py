#!/usr/bin/env python3
"""Verification plugin: ai-code-review.

External AI code review covering BOTH spec compliance AND standard
code review, through the LLM provider configured for the ``ai-code-review``
purpose (see ``ydk.core.plugin_llm``).

Uses git diff output for focused review of actual changes.
"""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

PURPOSE = "ai-code-review"

SYSTEM_PROMPT = """\
You are a senior code reviewer performing a comprehensive automated review.

Review the provided git diff covering TWO perspectives in one analysis:

## Perspective 1: Spec Compliance
- Does the implementation match the spec?
- Any deviations from interface contracts?
- Missing error scenarios defined in the spec?

## Perspective 2: Standard Code Review
- **DRY** — any duplicated logic?
- **YAGNI** — any unnecessary features or over-engineering?
- **SOLID** — single responsibility, dependency inversion violations?
- **Security** — injection, auth bypass, data exposure, secrets in code?
- **Best practices** — naming, error handling, test quality, readability?

For each finding, assign a severity:
- "critical" — must fix before merge (blocks)
- "warning" — should fix, noted in review
- "info" — optional improvement suggestion

And a category from:
- "spec_compliance" — deviation from spec
- "dry" — duplicated logic
- "yagni" — unnecessary code
- "solid" — design principle violation
- "security" — security issue
- "best_practices" — naming, error handling, test quality

Return your findings as the structured output. Set "passed" to false ONLY if
there are any "critical" findings. If no issues found, return an empty
findings list and passed=true.
"""

# Stack-specific review checklists, keyed by the language from
# ``ydk.core.stack_profile`` (passed as ``config.language``). Stacks without
# an entry get only the generic SYSTEM_PROMPT.
CHECKLISTS_DIR = Path(__file__).resolve().parent / "checklists"
STACK_CHECKLISTS = {"dotnet": "dotnet.md"}


def _stack_checklist(language: object) -> str:
    """Return the review checklist for *language*, or "" when the stack has none."""
    filename = STACK_CHECKLISTS.get(language) if isinstance(language, str) else None
    if filename is None:
        return ""
    return (CHECKLISTS_DIR / filename).read_text(encoding="utf-8")


class ReviewFinding(BaseModel):
    """One code review finding."""

    severity: Literal["critical", "warning", "info"]
    category: Literal["spec_compliance", "dry", "yagni", "solid", "security", "best_practices"]
    file: str
    description: str
    suggestion: str = ""


class ReviewResult(BaseModel):
    """Structured output of the ai-code-review LLM call."""

    findings: list[ReviewFinding] = Field(default_factory=list)
    summary: str
    passed: bool


def _read_files(root: Path, file_paths: list[str]) -> str:
    """Read and concatenate files, returning labeled content."""
    parts: list[str] = []
    for fp in file_paths:
        full = root / fp
        if full.is_file():
            try:
                content = full.read_text(encoding="utf-8", errors="replace")
                parts.append(f"--- {fp} ---\n{content}")
            except OSError:
                parts.append(f"--- {fp} --- (unreadable)")
    return "\n\n".join(parts)


def _resolve_diff_base(root: Path) -> str | None:
    """Return the merge-base SHA of HEAD and the base branch, or None if no base exists.

    Prefers ``origin/main`` (up to date after fetch) over a possibly stale local ``main``.
    """
    for ref in ("origin/main", "main"):
        try:
            result = subprocess.run(
                ["git", "merge-base", ref, "HEAD"],
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
        sha = result.stdout.strip()
        if result.returncode == 0 and sha:
            return sha
    return None


def _get_git_diff(root: Path, changed_files: list[str]) -> str:
    """Get git diff of changed files against the merge-base with the base branch."""
    base = _resolve_diff_base(root)
    if base is not None:
        try:
            result = subprocess.run(
                ["git", "diff", base, "--", *changed_files],
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Fallback: diff against HEAD
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--", *changed_files],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return ""


def _format_task_scope(task_scope: object) -> str:
    """Render the task-scope prompt block, or "" when no task scope is given."""
    if not isinstance(task_scope, dict) or not task_scope:
        return ""
    scope = cast("dict[str, Any]", task_scope)
    criteria = scope.get("acceptance_criteria") or []
    criteria_text = "\n".join(f"- {c}" for c in criteria) or "(none listed)"
    return (
        "\n\n=== TASK SCOPE ===\n\n"
        f"Title: {scope.get('title', '')}\n\n"
        f"Description:\n{scope.get('description', '')}\n\n"
        f"Acceptance criteria:\n{criteria_text}\n\n"
        "For spec compliance, consider ONLY the spec requirements owned by this task, as defined by "
        "the task scope above. Spec items outside this task's scope (e.g. work owned by sibling tasks) "
        "are not applicable: do not raise spec_compliance findings for them."
    )


def run_check(context: dict) -> dict:
    """Core check logic. Separated for testability."""
    from ydk.core.plugin_llm import run_plugin_llm

    start = time.time()
    project_root = Path(context["project_root"])
    changed_files = context.get("changed_files", [])
    spec_refs = context.get("spec_refs", [])
    config = context.get("config", {})

    if not changed_files:
        return {
            "name": "ai-code-review",
            "passed": True,
            "output": "No changed files to review",
            "duration_seconds": round(time.time() - start, 1),
            "detail": {"skipped": True},
        }

    # Get git diff instead of full file contents
    git_diff = _get_git_diff(project_root, changed_files)
    if not git_diff:
        # Fallback: read full files if diff is empty (new files)
        git_diff = _read_files(project_root, changed_files)

    system = SYSTEM_PROMPT
    checklist = _stack_checklist(config.get("language"))
    if checklist:
        system += "\n\n" + checklist
    spec_block = None
    if spec_refs:
        spec_content = _read_files(project_root, spec_refs)
        if spec_content:
            spec_block = "=== SPEC CONTENT (reference for compliance review) ===\n\n" + spec_content
    prompt = (
        "Review the following git diff for spec compliance and code quality:\n\n=== GIT DIFF ===\n\n"
        + git_diff
        + _format_task_scope(context.get("task_scope"))
    )

    outcome = run_plugin_llm(
        context,
        name="ai-code-review",
        purpose=PURPOSE,
        system=system,
        cacheable_context=spec_block,
        prompt=prompt,
        output_format=ReviewResult,
        kind="review",
        start=start,
    )
    if isinstance(outcome, dict):
        return outcome
    findings = [f.model_dump() for f in outcome.findings]
    summary = outcome.summary

    critical_count = sum(1 for f in findings if f.get("severity") == "critical")
    warning_count = sum(1 for f in findings if f.get("severity") == "warning")
    info_count = sum(1 for f in findings if f.get("severity") == "info")

    passed = critical_count == 0

    output_parts: list[str] = []
    if findings:
        for finding in findings:
            severity = finding.get("severity", "info").upper()
            category = finding.get("category", "")
            file_path = finding.get("file", "")
            description = finding.get("description", "")
            suggestion = finding.get("suggestion", "")
            output_parts.append(f"[{severity}] ({category}) {file_path}: {description}")
            if suggestion:
                output_parts.append(f"  Suggestion: {suggestion}")
    else:
        output_parts.append("No issues found")

    output_parts.append(f"\nTotals: {critical_count} critical, {warning_count} warnings, {info_count} info")
    if summary:
        output_parts.append(f"Summary: {summary}")

    return {
        "name": "ai-code-review",
        "passed": passed,
        "output": "\n".join(output_parts),
        "duration_seconds": round(time.time() - start, 1),
        "detail": {
            "findings": findings,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "info_count": info_count,
        },
    }


def main() -> None:
    """Run the ai-code-review verification check."""
    context = json.loads(sys.stdin.read())

    # Redirect stdout to stderr during check execution to capture any
    # debug/print output from third-party libraries.
    # This ensures ONLY our final JSON object goes to real stdout.
    real_stdout = sys.stdout
    sys.stdout = sys.stderr

    try:
        result = run_check(context)
    except Exception as exc:
        # A crash must never report PASS — emit a well-formed failing result
        result = {
            "name": "ai-code-review",
            "passed": False,
            "output": f"ERROR: plugin error - {exc}",
            "duration_seconds": 0,
            "detail": {"error": str(exc), "crashed": True, "no_cache": True},
        }
    finally:
        # Restore stdout before writing the result
        sys.stdout = real_stdout

    # Ensure EXACTLY one JSON object goes to stdout
    output = json.dumps(result)
    sys.stdout.write(output)
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

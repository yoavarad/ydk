#!/usr/bin/env python3
"""Verification plugin: spec-alignment.

Evaluates whether changed code aligns with referenced spec files
across 6 dimensions, calling the Anthropic API directly through the
shared YDK Claude client factory.

Uses git diff output (not full files) to focus on what actually changed.

Dimensions: entity accuracy, interface compliance, error handling,
boundary respect, scope compliance, cross-cutting adherence.
"""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

PURPOSE = "spec-alignment"

DIMENSIONS = [
    "entity_accuracy",
    "interface_compliance",
    "error_handling",
    "boundary_respect",
    "scope_compliance",
    "cross_cutting_adherence",
]

SYSTEM_PROMPT = """\
You are a senior software architect reviewing code changes for spec alignment.

Given the SPEC content and the GIT DIFF of changes, evaluate alignment across these 6 dimensions.
Score each 0-10 and provide brief reasoning.

Focus on the DIFF — it shows exactly what was added/modified. This is more useful than
reviewing full files because it highlights the actual changes being proposed.

Dimensions:
1. entity_accuracy — Do entities/models match the spec definitions?
2. interface_compliance — Do APIs/interfaces match spec signatures?
3. error_handling — Does error handling follow spec requirements?
4. boundary_respect — Are module boundaries respected per spec?
5. scope_compliance — Does the code stay within the spec's scope?
6. cross_cutting_adherence — Are cross-cutting concerns (logging, auth, etc.) handled per spec?

Return your scores and reasoning for each dimension as the structured output.
"""


class DimensionScore(BaseModel):
    """Score and reasoning for one alignment dimension."""

    score: float
    reasoning: str


class Dimensions(BaseModel):
    """Scores for every dimension in ``DIMENSIONS``."""

    entity_accuracy: DimensionScore
    interface_compliance: DimensionScore
    error_handling: DimensionScore
    boundary_respect: DimensionScore
    scope_compliance: DimensionScore
    cross_cutting_adherence: DimensionScore


class SpecEvaluation(BaseModel):
    """Structured output of the spec-alignment LLM call."""

    dimensions: Dimensions
    overall_score: float
    summary: str


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

    # Fallback: diff against HEAD (for cases where main doesn't exist)
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
        "Grade ONLY the spec requirements owned by this task, as defined by the task scope above. "
        "Spec items outside this task's scope (e.g. work owned by sibling tasks) are not applicable: "
        "exclude them from every dimension score, the overall score and the reasoning, and do not "
        "penalize their absence from the diff."
    )


def run_check(context: dict) -> dict:
    """Core check logic. Separated for testability."""
    from ydk.core.plugin_llm import run_plugin_llm

    start = time.time()
    project_root = Path(context["project_root"])
    changed_files = context.get("changed_files", [])
    spec_refs = context.get("spec_refs", [])
    config = context.get("config", {})
    spec_check_config = config.get("spec_check", {})

    if not changed_files:
        return {
            "name": "spec-alignment",
            "passed": True,
            "output": "No changed files to evaluate",
            "duration_seconds": round(time.time() - start, 1),
            "detail": {"skipped": True},
        }

    if not spec_refs:
        return {
            "name": "spec-alignment",
            "passed": True,
            "output": "No spec references provided — skipping alignment check",
            "duration_seconds": round(time.time() - start, 1),
            "detail": {"skipped": True},
        }

    # Read spec content
    spec_content = _read_files(project_root, spec_refs)

    # Get git diff instead of full file contents
    git_diff = _get_git_diff(project_root, changed_files)
    if not git_diff:
        # Fallback: read full files if diff is empty (new files)
        git_diff = _read_files(project_root, changed_files)

    spec_block = "=== SPEC CONTENT (reference) ===\n\n" + spec_content if spec_content else None
    prompt = (
        "Evaluate the following code changes (git diff) for spec alignment:\n\n=== GIT DIFF ===\n\n"
        + git_diff
        + _format_task_scope(context.get("task_scope"))
    )

    outcome = run_plugin_llm(
        context,
        name="spec-alignment",
        purpose=PURPOSE,
        system=SYSTEM_PROMPT,
        cacheable_context=spec_block,
        prompt=prompt,
        output_format=SpecEvaluation,
        kind="evaluation",
        start=start,
    )
    if isinstance(outcome, dict):
        return outcome
    overall_score = outcome.overall_score
    threshold = spec_check_config.get("thresholds", {}).get("architecture", 8)
    passed = overall_score >= threshold

    dimensions_detail = outcome.dimensions.model_dump()
    summary = outcome.summary

    output_parts = [f"Overall score: {overall_score:g}/10 (threshold: {threshold})"]
    for dim in DIMENSIONS:
        dim_data = dimensions_detail.get(dim, {})
        score = f"{dim_data['score']:g}"
        reasoning = dim_data.get("reasoning", "")
        output_parts.append(f"  {dim}: {score}/10 — {reasoning}")
    if summary:
        output_parts.append(f"\nSummary: {summary}")

    return {
        "name": "spec-alignment",
        "passed": passed,
        "output": "\n".join(output_parts),
        "duration_seconds": round(time.time() - start, 1),
        "detail": {
            "overall_score": overall_score,
            "threshold": threshold,
            "dimensions": dimensions_detail,
        },
    }


def main() -> None:
    """Run the spec-alignment verification check."""
    context = json.loads(sys.stdin.read())

    try:
        result = run_check(context)
    except Exception as exc:
        # A crash must never report PASS — emit a well-formed failing result
        result = {
            "name": "spec-alignment",
            "passed": False,
            "output": f"ERROR: plugin error - {exc}",
            "duration_seconds": 0,
            "detail": {"error": str(exc), "crashed": True, "no_cache": True},
        }
    json.dump(result, sys.stdout)
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

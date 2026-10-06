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

Call the submit_evaluation tool with your scores and reasoning for each dimension.
"""

EVALUATION_TOOL_SPEC = {
    "name": "submit_evaluation",
    "description": "Submit the structured spec-alignment evaluation result",
    "input_schema": {
        "type": "object",
        "properties": {
            "dimensions": {
                "type": "object",
                "properties": {
                    dim: {
                        "type": "object",
                        "properties": {
                            "score": {"type": "number"},
                            "reasoning": {"type": "string"},
                        },
                        "required": ["score", "reasoning"],
                    }
                    for dim in DIMENSIONS
                },
                "required": DIMENSIONS,
            },
            "overall_score": {"type": "number"},
            "summary": {"type": "string"},
        },
        "required": ["dimensions", "overall_score", "summary"],
    },
}


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


def _get_git_diff(root: Path, changed_files: list[str]) -> str:
    """Get git diff of changed files against main branch."""
    try:
        result = subprocess.run(
            ["git", "diff", "main", "--", *changed_files],
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


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_valid_evaluation(evaluation: Any) -> bool:
    """True when the model's submit_evaluation input has the expected dict shape."""
    if not isinstance(evaluation, dict):
        return False
    dims = evaluation.get("dimensions", {})
    if not isinstance(dims, dict) or not _is_number(evaluation.get("overall_score", 0)):
        return False
    return all(isinstance(d, dict) for d in dims.values())


def run_check(context: dict) -> dict:
    """Core check logic. Separated for testability."""
    from ydk.core.claude_client import (
        DEFAULT_API_KEY_ENV,
        ClaudeAPIError,
        MissingCredentialsError,
        build_client,
        create_message,
    )
    from ydk.models.config import AIConfig

    start = time.time()
    project_root = Path(context["project_root"])
    changed_files = context.get("changed_files", [])
    spec_refs = context.get("spec_refs", [])
    config = context.get("config", {})
    anthropic_config = config.get("anthropic", {})
    api_key_env = anthropic_config.get("api_key_env", DEFAULT_API_KEY_ENV)
    spec_check_config = config.get("spec_check", {})
    model_id = AIConfig(model_tiers=config.get("ai", {}).get("model_tiers", {})).model_for("review")

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

    try:
        client = build_client(api_key_env)
    except MissingCredentialsError as exc:
        return {
            "name": "spec-alignment",
            "passed": False,
            "output": (
                f"{exc} Set up credentials via the `ydk init` instructions, or disable "
                "this plugin by removing it from `verification.enabled` in .ydk/config.yaml "
                "if it is intentionally unused."
            ),
            "duration_seconds": round(time.time() - start, 1),
            "detail": {"credential_error": True, "no_cache": True},
        }

    # Read spec content
    spec_content = _read_files(project_root, spec_refs)

    # Get git diff instead of full file contents
    git_diff = _get_git_diff(project_root, changed_files)
    if not git_diff:
        # Fallback: read full files if diff is empty (new files)
        git_diff = _read_files(project_root, changed_files)

    system_blocks: list[dict] = [{"type": "text", "text": SYSTEM_PROMPT}]
    if spec_content:
        system_blocks.append(
            {
                "type": "text",
                "text": "=== SPEC CONTENT (reference) ===\n\n" + spec_content,
                "cache_control": {"type": "ephemeral"},
            }
        )

    user_message = (
        "Evaluate the following code changes (git diff) for spec alignment:\n\n=== GIT DIFF ===\n\n"
        + git_diff
        + _format_task_scope(context.get("task_scope"))
    )

    try:
        response = create_message(
            client,
            model=model_id,
            max_tokens=8192,
            system=system_blocks,
            messages=[{"role": "user", "content": user_message}],
            tools=[EVALUATION_TOOL_SPEC],
            tool_choice={"type": "tool", "name": "submit_evaluation"},
        )
    except ClaudeAPIError as exc:
        return {
            "name": "spec-alignment",
            "passed": False,
            "output": f"ERROR: {exc}",
            "duration_seconds": round(time.time() - start, 1),
            "detail": {"error": True, "no_cache": True},
        }

    tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use_block is None:
        return {
            "name": "spec-alignment",
            "passed": False,
            "output": "ERROR: no tool_use block in Anthropic response (unexpected)",
            "duration_seconds": round(time.time() - start, 1),
            "detail": {"error": True, "no_cache": True},
        }

    evaluation = cast("Any", tool_use_block).input
    if not _is_valid_evaluation(evaluation):
        return {
            "name": "spec-alignment",
            "passed": False,
            "output": "ERROR: malformed evaluation from model (unexpected submit_evaluation shape)",
            "duration_seconds": round(time.time() - start, 1),
            "detail": {"error": True, "malformed": True, "no_cache": True},
        }
    overall_score = evaluation.get("overall_score", 0)
    threshold = spec_check_config.get("thresholds", {}).get("architecture", 8)
    passed = overall_score >= threshold

    dimensions_detail = evaluation.get("dimensions", {})
    summary = evaluation.get("summary", "")

    output_parts = [f"Overall score: {overall_score}/10 (threshold: {threshold})"]
    for dim in DIMENSIONS:
        dim_data = dimensions_detail.get(dim, {})
        score = dim_data.get("score", "?")
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

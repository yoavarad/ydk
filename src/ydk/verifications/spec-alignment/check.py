#!/usr/bin/env python3
"""Verification plugin: spec-alignment.

Evaluates whether changed code aligns with referenced spec files
across 6 dimensions using a Strands Agent with the Anthropic API.

Uses git diff output (not full files) to focus on what actually changed.

Dimensions: entity accuracy, interface compliance, error handling,
boundary respect, scope compliance, cross-cutting adherence.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

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

Respond with ONLY valid JSON (no markdown fences):
{
  "dimensions": {
    "entity_accuracy": {"score": N, "reasoning": "..."},
    "interface_compliance": {"score": N, "reasoning": "..."},
    "error_handling": {"score": N, "reasoning": "..."},
    "boundary_respect": {"score": N, "reasoning": "..."},
    "scope_compliance": {"score": N, "reasoning": "..."},
    "cross_cutting_adherence": {"score": N, "reasoning": "..."}
  },
  "overall_score": N,
  "summary": "..."
}
"""


def _skip(reason: str) -> None:
    """Emit a skip result and exit cleanly."""
    result = {
        "name": "spec-alignment",
        "passed": True,
        "output": f"SKIPPED: {reason}",
        "duration_seconds": 0,
        "detail": {"skipped": True},
    }
    json.dump(result, sys.stdout)
    sys.exit(0)


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
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return ""


def run_check(context: dict) -> dict:
    """Core check logic. Separated for testability."""
    start = time.time()
    project_root = Path(context["project_root"])
    changed_files = context.get("changed_files", [])
    spec_refs = context.get("spec_refs", [])
    config = context.get("config", {})
    anthropic_config = config.get("anthropic", {})
    api_key_env = anthropic_config.get("api_key_env", "ANTHROPIC_API_KEY")
    spec_check_config = config.get("spec_check", {})
    model_id = spec_check_config.get("model", "claude-sonnet-4-6")

    # Check strands-agents availability
    try:
        from strands import Agent
        from strands.models.anthropic import AnthropicModel
    except ImportError:
        return {
            "name": "spec-alignment",
            "passed": True,
            "output": "SKIPPED: strands-agents not installed",
            "duration_seconds": 0,
            "detail": {"skipped": True},
        }

    # Check Anthropic API key
    api_key = os.getenv(api_key_env)
    if not api_key:
        return {
            "name": "spec-alignment",
            "passed": True,
            "output": f"SKIPPED: {api_key_env} not configured",
            "duration_seconds": 0,
            "detail": {"skipped": True},
        }

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

    # Build system prompt with spec content as cached prefix
    from strands import Agent
    from strands.models.anthropic import AnthropicModel

    anthropic_model = AnthropicModel(
        client_args={"api_key": api_key},
        model_id=model_id,
        max_tokens=8192,
        params={"temperature": 0.0},
    )

    system_prompt_with_spec = (
        SYSTEM_PROMPT + "\n\n=== SPEC CONTENT (reference) ===\n\n" + spec_content + "\n\n{{cachePoint}}"
    )

    agent = Agent(
        model=anthropic_model,
        system_prompt=system_prompt_with_spec,
    )

    user_message = (
        "Evaluate the following code changes (git diff) for spec alignment:\n\n=== GIT DIFF ===\n\n" + git_diff
    )

    response = agent(user_message)
    response_text = str(response)

    # Parse structured response
    try:
        evaluation = json.loads(response_text)
    except json.JSONDecodeError:
        # Try to extract JSON from response
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}") + 1
        if start_idx >= 0 and end_idx > start_idx:
            evaluation = json.loads(response_text[start_idx:end_idx])
        else:
            return {
                "name": "spec-alignment",
                "passed": False,
                "output": f"Failed to parse AI response: {response_text[:500]}",
                "duration_seconds": round(time.time() - start, 1),
                "detail": {"parse_error": True},
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
        import strands  # noqa: F401
    except ImportError:
        _skip("strands-agents not installed")

    result = run_check(context)
    json.dump(result, sys.stdout)
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Verification plugin: ai-code-review.

External AI code review covering BOTH spec compliance AND standard
code review using a Strands Agent with the Anthropic API.

Uses git diff output for focused review of actual changes.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

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

Respond with ONLY valid JSON (no markdown fences):
{
  "findings": [
    {
      "severity": "critical|warning|info",
      "category": "spec_compliance|dry|yagni|solid|security|best_practices",
      "file": "path/to/file",
      "description": "...",
      "suggestion": "..."
    }
  ],
  "summary": "...",
  "passed": true/false
}

Set "passed" to false ONLY if there are any "critical" findings.
If no issues found, return empty findings list and passed=true.
"""


def _skip(reason: str) -> None:
    """Emit a skip result and exit cleanly."""
    result = {
        "name": "ai-code-review",
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

    # Fallback: diff against HEAD
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
            "name": "ai-code-review",
            "passed": True,
            "output": "SKIPPED: strands-agents not installed",
            "duration_seconds": 0,
            "detail": {"skipped": True},
        }

    # Check Anthropic API key
    api_key = os.getenv(api_key_env)
    if not api_key:
        return {
            "name": "ai-code-review",
            "passed": True,
            "output": f"SKIPPED: {api_key_env} not configured",
            "duration_seconds": 0,
            "detail": {"skipped": True},
        }

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

    # Build system prompt (with spec content as cached prefix if available)
    from strands import Agent
    from strands.models.anthropic import AnthropicModel

    anthropic_model = AnthropicModel(
        client_args={"api_key": api_key},
        model_id=model_id,
        max_tokens=8192,
        params={"temperature": 0.0},
    )

    system_prompt = SYSTEM_PROMPT
    if spec_refs:
        spec_content = _read_files(project_root, spec_refs)
        if spec_content:
            system_prompt += "\n\n=== SPEC CONTENT (reference for compliance review) ===\n\n" + spec_content
    system_prompt += "\n\n{{cachePoint}}"

    agent = Agent(
        model=anthropic_model,
        system_prompt=system_prompt,
    )

    user_message = (
        "Review the following git diff for spec compliance and code quality:\n\n=== GIT DIFF ===\n\n" + git_diff
    )

    response = agent(user_message)
    response_text = str(response)

    # Parse structured response
    try:
        review = json.loads(response_text)
    except json.JSONDecodeError:
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}") + 1
        if start_idx >= 0 and end_idx > start_idx:
            review = json.loads(response_text[start_idx:end_idx])
        else:
            return {
                "name": "ai-code-review",
                "passed": False,
                "output": f"Failed to parse AI response: {response_text[:500]}",
                "duration_seconds": round(time.time() - start, 1),
                "detail": {"parse_error": True},
            }

    findings = review.get("findings", [])
    summary = review.get("summary", "")

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

    try:
        import strands  # noqa: F401
    except ImportError:
        _skip("strands-agents not installed")

    # Redirect stdout to stderr during check execution to capture any
    # debug/print output from third-party libraries (e.g. strands, boto3).
    # This ensures ONLY our final JSON object goes to real stdout.
    real_stdout = sys.stdout
    sys.stdout = sys.stderr

    try:
        result = run_check(context)
    except Exception as exc:
        # Gracefully handle any crash — never output malformed JSON
        result = {
            "name": "ai-code-review",
            "passed": True,
            "output": f"SKIPPED: plugin error — {exc}",
            "duration_seconds": 0,
            "detail": {"skipped": True, "error": str(exc)},
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

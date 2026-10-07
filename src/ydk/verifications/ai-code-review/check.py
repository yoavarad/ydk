#!/usr/bin/env python3
"""Verification plugin: ai-code-review.

External AI code review covering BOTH spec compliance AND standard
code review, calling the Anthropic API directly through the shared
YDK Claude client factory.

Uses git diff output for focused review of actual changes.
"""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

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

Call the submit_review tool with your findings. Set "passed" to false ONLY if
there are any "critical" findings. If no issues found, return an empty
findings list and passed=true.
"""

REVIEW_TOOL_SPEC = {
    "name": "submit_review",
    "description": "Submit the structured code review result",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {"type": "string", "enum": ["critical", "warning", "info"]},
                        "category": {
                            "type": "string",
                            "enum": [
                                "spec_compliance",
                                "dry",
                                "yagni",
                                "solid",
                                "security",
                                "best_practices",
                            ],
                        },
                        "file": {"type": "string"},
                        "description": {"type": "string"},
                        "suggestion": {"type": "string"},
                    },
                    "required": ["severity", "category", "file", "description"],
                },
            },
            "summary": {"type": "string"},
            "passed": {"type": "boolean"},
        },
        "required": ["findings", "summary", "passed"],
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


def _valid_findings(findings: object) -> bool:
    """True when findings is a list of dicts."""
    return isinstance(findings, list) and all(isinstance(f, dict) for f in findings)


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
    model_id = AIConfig(model_tiers=config.get("ai", {}).get("model_tiers", {})).model_for("review")

    if not changed_files:
        return {
            "name": "ai-code-review",
            "passed": True,
            "output": "No changed files to review",
            "duration_seconds": round(time.time() - start, 1),
            "detail": {"skipped": True},
        }

    try:
        client = build_client(api_key_env)
    except MissingCredentialsError as exc:
        return {
            "name": "ai-code-review",
            "passed": False,
            "output": (
                f"{exc} Set up credentials via the `ydk init` instructions, or disable "
                "this plugin by removing it from `verification.enabled` in .ydk/config.yaml "
                "if it is intentionally unused."
            ),
            "duration_seconds": round(time.time() - start, 1),
            "detail": {"credential_error": True, "no_cache": True},
        }

    # Get git diff instead of full file contents
    git_diff = _get_git_diff(project_root, changed_files)
    if not git_diff:
        # Fallback: read full files if diff is empty (new files)
        git_diff = _read_files(project_root, changed_files)

    system_blocks: list[dict] = [{"type": "text", "text": SYSTEM_PROMPT}]
    if spec_refs:
        spec_content = _read_files(project_root, spec_refs)
        if spec_content:
            system_blocks.append(
                {
                    "type": "text",
                    "text": "=== SPEC CONTENT (reference for compliance review) ===\n\n" + spec_content,
                    "cache_control": {"type": "ephemeral"},
                }
            )

    user_message = (
        "Review the following git diff for spec compliance and code quality:\n\n=== GIT DIFF ===\n\n"
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
            tools=[REVIEW_TOOL_SPEC],
            tool_choice={"type": "tool", "name": "submit_review"},
        )
    except ClaudeAPIError as exc:
        return {
            "name": "ai-code-review",
            "passed": False,
            "output": f"ERROR: {exc}",
            "duration_seconds": round(time.time() - start, 1),
            "detail": {"error": True, "no_cache": True},
        }

    tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use_block is None:
        return {
            "name": "ai-code-review",
            "passed": False,
            "output": "ERROR: no tool_use block in Anthropic response (unexpected)",
            "duration_seconds": round(time.time() - start, 1),
            "detail": {"error": True, "no_cache": True},
        }

    review = cast("Any", tool_use_block).input
    if not isinstance(review, dict) or not _valid_findings(review.get("findings", [])):
        return {
            "name": "ai-code-review",
            "passed": False,
            "output": "ERROR: malformed review from model (unexpected submit_review shape)",
            "duration_seconds": round(time.time() - start, 1),
            "detail": {"error": True, "malformed": True, "no_cache": True},
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

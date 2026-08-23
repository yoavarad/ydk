#!/usr/bin/env python3
"""Verification plugin: validate PR body contains required proof artifacts.

Checks that a PR body includes:
- At least one ```console, ```text, or ```bash code block (proof of command output)
- A ``## Summary`` section
- A ``## Test Plan`` or ``## Test plan`` section
- Screenshot links/attachments when UI files (.tsx, .jsx, .css, .html, .js in visual/overlay) changed
"""

import json
import re
import sys
import time

# File extensions and path patterns that indicate UI changes
_UI_EXTENSIONS = {".tsx", ".jsx", ".css", ".html"}
_UI_PATH_PATTERNS = {"visual/", "overlay/"}
_UI_JS_PATHS = {"visual/", "overlay/"}  # .js files only count as UI in these paths


def _has_console_block(body: str) -> bool:
    """Check for at least one ```console, ```text, or ```bash code block."""
    return bool(re.search(r"```(?:console|text|bash)", body))


def _has_summary_section(body: str) -> bool:
    """Check for a ## Summary section (case-insensitive)."""
    return bool(re.search(r"^##\s+[Ss]ummary", body, re.MULTILINE))


def _has_test_plan_section(body: str) -> bool:
    """Check for a ## Test Plan or ## Test plan section."""
    return bool(re.search(r"^##\s+[Tt]est\s+[Pp]lan", body, re.MULTILINE))


def _has_screenshots(body: str) -> bool:
    """Check for screenshot references (image markdown or explicit section)."""
    if re.search(r"^##\s+[Ss]creenshots?", body, re.MULTILINE):
        return True
    # Check for image markdown links
    return bool(re.search(r"!\[.*?\]\(.*?\)", body))


def _is_ui_file(filepath: str) -> bool:
    """Determine if a changed file is a UI file that would require screenshots."""
    lower = filepath.lower()
    # Check extension-based UI files
    for ext in _UI_EXTENSIONS:
        if lower.endswith(ext):
            return True
    # .js files only count if they're in visual/overlay paths
    if lower.endswith(".js"):
        for pattern in _UI_JS_PATHS:
            if pattern in lower:
                return True
    return False


def _needs_screenshots(changed_files: list[str] | None) -> bool:
    """Return True if any changed file is a UI file.

    ``changed_files`` may be explicitly ``None`` (not just absent) -- callers
    like ``Verifier.run_all()`` use ``None`` as a "scope to everything" signal
    for other plugins, and that same context dict gets reused here.
    """
    return any(_is_ui_file(f) for f in changed_files or [])


def validate_pr_body(body: str, changed_files: list[str] | None) -> dict:
    """Validate a PR body and return a structured result.

    Returns a dict with:
    - passed: bool
    - missing: list of requirement keys that are not met
    - met: list of requirement keys that are met
    - details: human-readable description of each check
    """
    missing: list[str] = []
    met: list[str] = []
    details: list[str] = []

    # Check console block
    if _has_console_block(body):
        met.append("console_block")
        details.append("PASS: PR body contains command output in code block")
    else:
        missing.append("console_block")
        details.append("FAIL: PR body must contain actual command output in ```console, ```text, or ```bash block")

    # Check summary section
    if _has_summary_section(body):
        met.append("summary_section")
        details.append("PASS: PR body contains ## Summary section")
    else:
        missing.append("summary_section")
        details.append("FAIL: PR body must contain a ## Summary section")

    # Check test plan section
    if _has_test_plan_section(body):
        met.append("test_plan_section")
        details.append("PASS: PR body contains ## Test Plan section")
    else:
        missing.append("test_plan_section")
        details.append("FAIL: PR body must contain a ## Test Plan section")

    # Check screenshots for UI files
    if _needs_screenshots(changed_files):
        if _has_screenshots(body):
            met.append("screenshot_for_ui")
            details.append("PASS: PR body contains screenshots for UI changes")
        else:
            missing.append("screenshot_for_ui")
            details.append("FAIL: UI file changes detected — PR body must include screenshots")
    else:
        met.append("screenshot_for_ui_not_needed")
        details.append("SKIP: No UI files changed — screenshots not required")

    return {
        "passed": len(missing) == 0,
        "missing": missing,
        "met": met,
        "details": details,
    }


def main() -> None:
    """Run the pr-body-validation verification check."""
    context = json.loads(sys.stdin.read())
    _project_root = context["project_root"]  # required by plugin contract
    pr_body = context.get("pr_body", "")
    changed_files = context.get("changed_files", [])
    start = time.time()

    result = validate_pr_body(pr_body, changed_files)

    output_lines = result["details"]
    if result["passed"]:
        output = "PASS: All PR body requirements met\n" + "\n".join(output_lines)
    else:
        output = f"FAIL: Missing requirements: {', '.join(result['missing'])}\n" + "\n".join(output_lines)

    check_result = {
        "name": "pr-body-validation",
        "passed": result["passed"],
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {
            "missing": result["missing"],
            "met": result["met"],
        },
    }
    json.dump(check_result, sys.stdout)
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

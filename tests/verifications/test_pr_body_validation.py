"""Tests for the pr-body-validation verification plugin.

Covers: the plugin must not crash when ``changed_files`` is present in the
context but explicitly ``None`` (as opposed to simply absent). This happens
in practice because ``Verifier.run_all()`` mutates the shared context dict,
setting ``changed_files`` to ``None`` as an internal "scope to everything"
signal when there's no committed diff vs main yet -- and ``task_lifecycle``
reuses that same dict for this plugin's separate PR-body gate.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import types

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "pr-body-validation" / "check.py"

_VALID_BODY = "## Summary\n\ntext\n\n## Test Plan\n\n```console\nok\n```\n"


def _load_check_module() -> types.ModuleType:
    """Import pr-body-validation's check.py as a module for direct testing."""
    spec = importlib.util.spec_from_file_location("pr_body_validation_check", CHECK_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_check(context: dict) -> dict:
    result = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        input=json.dumps(context),
        capture_output=True,
        text=True,
    )
    assert result.returncode in (0, 1), f"unexpected crash: {result.stderr}"
    return json.loads(result.stdout)


def test_needs_screenshots_none_changed_files_is_falsy() -> None:
    module = _load_check_module()
    assert module._needs_screenshots(None) is False


def test_validate_pr_body_none_changed_files_does_not_crash() -> None:
    module = _load_check_module()
    result = module.validate_pr_body(_VALID_BODY, None)
    assert result["passed"] is True


def test_subprocess_passes_with_null_changed_files_in_context() -> None:
    data = _run_check({"project_root": ".", "pr_body": _VALID_BODY, "changed_files": None})
    assert data["passed"] is True


def test_subprocess_passes_with_absent_changed_files_in_context() -> None:
    data = _run_check({"project_root": ".", "pr_body": _VALID_BODY})
    assert data["passed"] is True

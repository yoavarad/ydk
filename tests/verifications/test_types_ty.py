"""Tests for the types-ty verification plugin's graceful degradation.

Covers: skip (not fail) when ``ty`` isn't on PATH, e.g. a non-Python
project or a machine where ty isn't installed (GitHub issue #3).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

CHECK_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "verifications" / "types-ty" / "check.py"


def test_skips_when_ty_not_on_path(tmp_path: Path) -> None:
    """When ty isn't installed, the plugin passes (skips) instead of crashing."""
    env = dict(os.environ)
    env["PATH"] = ""
    result = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        input=json.dumps({"project_root": str(tmp_path)}),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["passed"] is True
    assert "ty not found" in data["output"]

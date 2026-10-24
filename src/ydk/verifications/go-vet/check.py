#!/usr/bin/env python3
"""Verification plugin: go-vet.

Runs ``go vet ./...`` (with ``-tags`` from ``verification.go.test_tags``).
Skips when no Go-relevant files changed, the go toolchain is missing, or
the project has no go.mod.
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _is_go_relevant(path: str) -> bool:
    """True for *.go, go.mod, go.sum, or anything under a vendor/ directory."""
    parts = path.replace("\\", "/").split("/")
    return parts[-1].lower().endswith(".go") or parts[-1] in ("go.mod", "go.sum") or "vendor" in parts[:-1]


def _result(passed: bool, output: str, start: float, detail: dict | None = None) -> dict:
    return {
        "name": "go-vet",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": detail,
    }


def _skipped(reason: str, start: float) -> dict:
    return _result(True, reason, start, {"status": "SKIPPED", "skip_reason": reason})


def _emit(result: dict) -> None:
    json.dump(result, sys.stdout)
    sys.exit(0 if result["passed"] else 1)


def main() -> None:
    """Run the go-vet verification check."""
    context = json.loads(sys.stdin.read())
    root = Path(context["project_root"])
    start = time.time()
    go_config = (context.get("config") or {}).get("go") or {}

    changed_files = context.get("changed_files")
    if changed_files and not any(_is_go_relevant(f) for f in changed_files):
        _emit(_skipped("No relevant files changed (*.go, go.mod, go.sum, vendor/) — skipped", start))
        return

    go_bin = shutil.which("go")
    if go_bin is None:
        _emit(_skipped("go toolchain not found — skipped (install from https://go.dev/dl/)", start))
        return
    if not (root / "go.mod").is_file():
        _emit(_skipped("No go.mod found — skipped (non-Go project?)", start))
        return

    tags = go_config.get("test_tags") or []
    cmd = [go_bin, "vet", *(["-tags", ",".join(tags)] if tags else []), "./..."]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(root),
            timeout=170,
            check=False,
        )
    except subprocess.TimeoutExpired:
        _emit(_result(False, "go vet timed out after 170s", start, {"command": cmd}))
        return
    output = (proc.stdout + ("\n" + proc.stderr if proc.stderr else "")).strip()
    _emit(_result(proc.returncode == 0, output or "go vet reported no issues", start, {"command": cmd}))


if __name__ == "__main__":
    main()

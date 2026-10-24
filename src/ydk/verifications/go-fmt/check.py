#!/usr/bin/env python3
"""Verification plugin: go-fmt.

Fails when ``gofmt -l`` lists any unformatted Go file, naming each one.
Skips when no Go-relevant files changed, the go toolchain is missing, or
the project has no go.mod. vendor/ and hidden directories are not checked.
With ``auto_fix`` in the context (``verify run --auto-fix``), the listed
files are rewritten with ``gofmt -w`` instead of failing.
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

_SKIP_DIRS = {"vendor", "node_modules", "testdata"}


def _is_go_relevant(path: str) -> bool:
    """True for *.go, go.mod, go.sum, or anything under a vendor/ directory."""
    parts = path.replace("\\", "/").split("/")
    return parts[-1].lower().endswith(".go") or parts[-1] in ("go.mod", "go.sum") or "vendor" in parts[:-1]


def _result(passed: bool, output: str, start: float, detail: dict | None = None) -> dict:
    return {
        "name": "go-fmt",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": detail,
    }


def _ignored(path: str) -> bool:
    """True for gofmt hits inside nested vendor/, testdata/ or node_modules/ dirs."""
    return bool(_SKIP_DIRS & set(path.replace("\\", "/").split("/")[:-1]))


def _format_targets(root: Path) -> list[str]:
    """Top-level dirs and .go files to hand gofmt, excluding vendor/ and hidden dirs."""
    targets = []
    for entry in sorted(root.iterdir()):
        if entry.name.startswith(".") or entry.name in _SKIP_DIRS:
            continue
        if entry.is_dir() or entry.suffix == ".go":
            targets.append(entry.name)
    return targets


def _auto_fix(gofmt_bin: str, root: Path, files: list[str], start: float) -> dict:
    """Rewrite *files* in place with ``gofmt -w`` (``verify run --auto-fix``)."""
    try:
        proc = subprocess.run(
            [gofmt_bin, "-w", *files],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(root),
            timeout=55,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _result(False, "gofmt -w timed out after 55s", start, {"files": files})
    if proc.returncode != 0:
        return _result(False, (proc.stderr or proc.stdout).strip(), start, {"files": files})
    listing = "\n".join(f"  {f}" for f in files)
    detail = {"files": files, "auto_fixed_count": len(files)}
    return _result(True, f"gofmt -w reformatted {len(files)} file(s):\n{listing}", start, detail)


def _skipped(reason: str, start: float) -> dict:
    return _result(True, reason, start, {"status": "SKIPPED", "skip_reason": reason})


def _emit(result: dict) -> None:
    json.dump(result, sys.stdout)
    sys.exit(0 if result["passed"] else 1)


def main() -> None:
    """Run the go-fmt verification check."""
    context = json.loads(sys.stdin.read())
    root = Path(context["project_root"])
    start = time.time()

    changed_files = context.get("changed_files")
    if changed_files and not any(_is_go_relevant(f) for f in changed_files):
        _emit(_skipped("No relevant files changed (*.go, go.mod, go.sum, vendor/) — skipped", start))
        return

    gofmt_bin = shutil.which("gofmt")
    if gofmt_bin is None:
        _emit(_skipped("gofmt not found — skipped (install Go from https://go.dev/dl/)", start))
        return
    if not (root / "go.mod").is_file():
        _emit(_skipped("No go.mod found — skipped (non-Go project?)", start))
        return

    try:
        proc = subprocess.run(
            [gofmt_bin, "-l", *_format_targets(root)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(root),
            timeout=55,
            check=False,
        )
    except subprocess.TimeoutExpired:
        _emit(_result(False, "gofmt timed out after 55s", start))
        return
    files = [f for f in (line.strip() for line in proc.stdout.splitlines()) if f and not _ignored(f)]
    if proc.returncode != 0:
        _emit(_result(False, (proc.stderr or proc.stdout).strip(), start, {"files": files}))
        return
    if files and context.get("auto_fix"):
        # Only rewrite changed files; pre-existing unformatted files elsewhere still fail.
        changed = {f.replace("\\", "/") for f in changed_files or []}
        fixable = [f for f in files if not changed or f in changed]
        rest = [f for f in files if f not in fixable]
        result = _auto_fix(gofmt_bin, root, fixable, start) if fixable else _result(True, "", start)
        if result["passed"] and rest:
            listing = "\n".join(f"  {f}" for f in rest)
            msg = f"gofmt found unformatted files outside the change (run `gofmt -w`):\n{listing}"
            result = _result(False, msg, start, {"files": rest, "auto_fixed_count": len(fixable)})
        _emit(result)
        return
    if files:
        listing = "\n".join(f"  {f}" for f in files)
        _emit(_result(False, f"gofmt found unformatted files (run `gofmt -w`):\n{listing}", start, {"files": files}))
        return
    _emit(_result(True, "All Go files are gofmt-formatted", start, {"files": []}))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Verification plugin: go-vendor.

For air-gapped builds with a committed vendor/: regenerates the vendor tree
with ``go mod vendor -o <tmp>`` (never touching the working tree), fails if
it differs from vendor/, then requires ``go build -mod=vendor ./...`` to
succeed. Skips when no Go-relevant files changed, the go toolchain is
missing, or the project has no go.mod or no vendor/ directory.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_MAX_LISTED = 20
_TIMEOUT = 140


def _is_go_relevant(path: str) -> bool:
    """True for *.go, go.mod, go.sum, or anything under a vendor/ directory."""
    parts = path.replace("\\", "/").split("/")
    return parts[-1].lower().endswith(".go") or parts[-1] in ("go.mod", "go.sum") or "vendor" in parts[:-1]


def _result(passed: bool, output: str, start: float, detail: dict | None = None) -> dict:
    return {
        "name": "go-vendor",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": detail,
    }


def _emit(result: dict) -> None:
    json.dump(result, sys.stdout)
    sys.exit(0 if result["passed"] else 1)


def _files(root: Path) -> dict[str, Path]:
    return {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}


def _content(path: Path) -> bytes:
    """File bytes with CRLF folded to LF, so core.autocrlf checkouts don't look stale."""
    return path.read_bytes().replace(b"\r\n", b"\n")


def _diff_trees(committed: Path, regenerated: Path) -> list[str]:
    """Sorted relative paths that were added, removed, or changed between two trees."""
    left, right = _files(committed), _files(regenerated)
    differing = set(left) ^ set(right)
    differing |= {rel for rel in set(left) & set(right) if _content(left[rel]) != _content(right[rel])}
    return sorted(differing)


def _run(cmd: list[str], root: Path) -> subprocess.CompletedProcess:
    """Run a go command; a timeout comes back as a failed CompletedProcess, not an exception."""
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(root),
            timeout=_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, -1, "", f"{' '.join(cmd[1:3])} timed out after {_TIMEOUT}s")


def _combined(proc: subprocess.CompletedProcess) -> str:
    return (proc.stdout + ("\n" + proc.stderr if proc.stderr else "")).strip()


def main() -> None:
    """Run the go-vendor verification check."""
    context = json.loads(sys.stdin.read())
    root = Path(context["project_root"])
    start = time.time()

    changed_files = context.get("changed_files")
    if changed_files and not any(_is_go_relevant(f) for f in changed_files):
        _emit(_result(True, "No relevant files changed (*.go, go.mod, go.sum, vendor/) — skipped", start))
        return

    go_bin = shutil.which("go")
    if go_bin is None:
        _emit(_result(True, "go toolchain not found — skipped (install from https://go.dev/dl/)", start))
        return
    if not (root / "go.mod").is_file():
        _emit(_result(True, "No go.mod found — skipped (non-Go project?)", start))
        return
    if not (root / "vendor").is_dir():
        _emit(_result(True, "No vendor/ directory — skipped (module is not vendored)", start))
        return

    with tempfile.TemporaryDirectory() as tmp:
        regenerated = Path(tmp) / "vendor"
        proc = _run([go_bin, "mod", "vendor", "-o", str(regenerated)], root)
        if proc.returncode != 0:
            _emit(_result(False, f"go mod vendor -o (Go 1.18+) failed:\n{_combined(proc)}", start))
            return
        stale = _diff_trees(root / "vendor", regenerated)
    if stale:
        listing = "\n".join(f"  vendor/{rel}" for rel in stale[:_MAX_LISTED])
        more = f"\n  ... and {len(stale) - _MAX_LISTED} more" if len(stale) > _MAX_LISTED else ""
        output = f"vendor/ is stale — run `go mod vendor` and commit the result:\n{listing}{more}"
        _emit(_result(False, output, start, {"stale_files": stale}))
        return

    build_cmd = [go_bin, "build", "-mod=vendor", "./..."]
    build = _run(build_cmd, root)
    output = _combined(build) or "vendor/ is fresh and go build -mod=vendor succeeded"
    _emit(_result(build.returncode == 0, output, start, {"stale_files": [], "command": build_cmd}))


if __name__ == "__main__":
    main()

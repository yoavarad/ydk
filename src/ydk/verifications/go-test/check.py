#!/usr/bin/env python3
"""Verification plugin: go-test.

Runs ``go test [-race] [-tags ...] -coverprofile=<tmp> ./...`` and parses
per-package coverage from its output. When ``verification.go.coverage_min``
is above zero, every package matching ``verification.go.coverage_packages``
(globs over module-relative or full import paths; empty = whole module)
must reach it. Note: Go 1.22+ reports packages without tests as 0.0%, so
with an empty package list such packages (e.g. ``cmd/...``) fail the gate.

Skips when no Go-relevant files changed, the go toolchain is missing, or
the project has no go.mod. ``detail.summary`` (package ok/FAIL counts and the
statement-weighted total coverage from the coverprofile) is shown in the PR body.
"""

import fnmatch
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_COVERAGE_RE = re.compile(r"^[ \t]*(?:ok[ \t]+)?(\S+)[ \t].*?coverage: (\d+(?:\.\d+)?)% of statements", re.MULTILINE)
_MODULE_RE = re.compile(r"^module\s+(\S+)", re.MULTILINE)
# Package result lines: "ok  <pkg> ...", "FAIL\t<pkg> ..." (bare "FAIL" and "--- FAIL:" excluded).
_OK_RE = re.compile(r"^ok[ \t]+\S+", re.MULTILINE)
_FAIL_RE = re.compile(r"^FAIL[ \t]+\S+", re.MULTILINE)


def _is_go_relevant(path: str) -> bool:
    """True for *.go, go.mod, go.sum, or anything under a vendor/ directory."""
    parts = path.replace("\\", "/").split("/")
    return parts[-1].lower().endswith(".go") or parts[-1] in ("go.mod", "go.sum") or "vendor" in parts[:-1]


def _result(passed: bool, output: str, start: float, detail: dict | None = None) -> dict:
    return {
        "name": "go-test",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": detail,
    }


def _emit(result: dict) -> None:
    json.dump(result, sys.stdout)
    sys.exit(0 if result["passed"] else 1)


def _module_path(root: Path) -> str | None:
    """Read the ``module`` directive from go.mod."""
    match = _MODULE_RE.search((root / "go.mod").read_text(encoding="utf-8", errors="replace"))
    return match.group(1) if match else None


def _parse_coverage(output: str) -> dict[str, float]:
    """Map import path -> coverage % from ``go test -cover`` output lines."""
    return {m.group(1): float(m.group(2)) for m in _COVERAGE_RE.finditer(output)}


def _total_coverage(profile: str) -> float | None:
    """Statement-weighted total % from a coverprofile (duplicate blocks merged), like ``go tool cover -func``."""
    blocks: dict[str, tuple[int, int]] = {}
    for line in profile.splitlines()[1:]:
        parts = line.rsplit(" ", 2)
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
            continue
        stmts, count = int(parts[1]), int(parts[2])
        prev = blocks.get(parts[0], (stmts, 0))
        blocks[parts[0]] = (stmts, max(prev[1], count))
    total = sum(s for s, _ in blocks.values())
    if not total:
        return None
    return 100.0 * sum(s for s, c in blocks.values() if c > 0) / total


def _summary(stdout: str, total: float | None) -> str:
    """One-line PR summary: package ok/FAIL counts plus total coverage when known."""
    line = f"{len(_OK_RE.findall(stdout))} package(s) ok, {len(_FAIL_RE.findall(stdout))} FAIL"
    return line + (f", total coverage {total:.1f}%" if total is not None else "")


def _relative(pkg: str, module: str | None) -> str:
    if module and pkg == module:
        return "."
    if module and pkg.startswith(module + "/"):
        return pkg[len(module) + 1 :]
    return pkg


def _below_threshold(
    coverage: dict[str, float], module: str | None, minimum: float, patterns: list[str]
) -> list[tuple[str, float]]:
    """Return (module-relative package, %) for gated packages under ``minimum``, sorted by package."""
    if minimum <= 0:
        return []
    failures = []
    for pkg, pct in coverage.items():
        rel = _relative(pkg, module)
        if patterns and not any(fnmatch.fnmatchcase(rel, p) or fnmatch.fnmatchcase(pkg, p) for p in patterns):
            continue
        if pct < minimum:
            failures.append((rel, pct))
    return sorted(failures)


def _build_command(go_bin: str, go_config: dict, profile: str) -> list[str]:
    cmd = [go_bin, "test"]
    if go_config.get("race", True):
        cmd.append("-race")
    tags = go_config.get("test_tags") or []
    if tags:
        cmd += ["-tags", ",".join(tags)]
    return [*cmd, f"-coverprofile={profile}", "./..."]


def main() -> None:
    """Run the go-test verification check."""
    context = json.loads(sys.stdin.read())
    root = Path(context["project_root"])
    start = time.time()
    go_config = (context.get("config") or {}).get("go") or {}

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

    with tempfile.TemporaryDirectory() as tmp:
        cmd = _build_command(go_bin, go_config, str(Path(tmp) / "coverage.out"))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(root),
                timeout=590,
                check=False,
            )
        except subprocess.TimeoutExpired:
            _emit(_result(False, "go test timed out after 590s", start, {"command": cmd}))
            return
        profile_path = Path(tmp) / "coverage.out"
        total = (
            _total_coverage(profile_path.read_text(encoding="utf-8", errors="replace"))
            if proc.returncode == 0 and profile_path.is_file()  # failed runs leave a partial profile
            else None
        )
    output = (proc.stdout + ("\n" + proc.stderr if proc.stderr else "")).strip()
    coverage = _parse_coverage(proc.stdout)
    minimum = float(go_config.get("coverage_min") or 0.0)
    failures = _below_threshold(coverage, _module_path(root), minimum, go_config.get("coverage_packages") or [])

    if failures:
        listing = "\n".join(f"  {pkg}: {pct:.1f}%" for pkg, pct in failures)
        output += f"\n\nCoverage below {minimum:.1f}%:\n{listing}"
    passed = proc.returncode == 0 and not failures
    detail = {
        "command": cmd,
        "coverage": coverage,
        "coverage_min": minimum,
        "below_threshold": dict(failures),
        "coverage_total": total,
        "summary": _summary(proc.stdout, total),
    }
    _emit(_result(passed, output, start, detail))


if __name__ == "__main__":
    main()

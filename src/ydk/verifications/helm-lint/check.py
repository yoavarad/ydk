#!/usr/bin/env python3
"""Verification plugin: helm lint + values.schema.json validation.

For each chart dir (``verification.helm.charts``, default: every dir holding a
Chart.yaml) runs ``helm lint --strict`` and ``helm template`` once per file in
``verification.helm.values_files`` (resolved relative to the chart dir), which
surfaces values.schema.json violations. Fails when ``require_schema`` is set
and a chart has no values.schema.json.
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _finish(passed: bool, output: str, start: float) -> None:
    json.dump(
        {
            "name": "helm-lint",
            "passed": passed,
            "output": output,
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        },
        sys.stdout,
    )
    sys.exit(0 if passed else 1)


def _discover_charts(root: Path) -> list[Path]:
    found = []
    for chart_yaml in sorted(root.rglob("Chart.yaml")):
        rel_parts = set(chart_yaml.relative_to(root).parts[:-1])
        if rel_parts & {".git", ".ydk", "node_modules"}:
            continue
        found.append(chart_yaml.parent)
    return found


def _chart_changed(chart: Path, root: Path, changed_files: list[str]) -> bool:
    for f in changed_files:
        path = (root / f).resolve()
        if path.is_relative_to(chart.resolve()):
            return True
    return False


def _run(cmd: list[str], cwd: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            timeout=100,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{cmd[1]} could not run: {exc}"
    out = (proc.stdout + ("\n" + proc.stderr if proc.stderr else "")).strip()
    return proc.returncode == 0, out


def main() -> None:
    """Run the helm-lint verification check."""
    context = json.loads(sys.stdin.read())
    root = Path(context["project_root"])
    cfg = (context.get("config") or {}).get("helm") or {}
    start = time.time()

    if not shutil.which("helm"):
        _finish(True, "helm not installed — skipped (install from https://helm.sh)", start)

    charts = [root / c for c in cfg["charts"]] if cfg.get("charts") else _discover_charts(root)
    charts = [c for c in charts if (c / "Chart.yaml").is_file()]
    if not charts:
        _finish(True, "No Helm charts (Chart.yaml) found — skipped", start)

    changed_files = context.get("changed_files")
    if changed_files:
        charts = [c for c in charts if _chart_changed(c, root, changed_files)]
        if not charts:
            _finish(True, "No Helm chart files changed — skipped", start)

    failures: list[str] = []
    for chart in charts:
        name = chart.relative_to(root).as_posix() if chart.is_relative_to(root) else str(chart)
        if cfg.get("require_schema") and not (chart / "values.schema.json").is_file():
            failures.append(f"{name}: values.schema.json missing (verification.helm.require_schema is true)")
        ok, out = _run(["helm", "lint", "--strict", str(chart)], str(root))
        if not ok:
            failures.append(f"{name}: helm lint failed\n{out}")
        for vf in cfg.get("values_files") or []:
            values_path = chart / vf
            if not values_path.is_file():
                failures.append(f"{name}: configured values file not found: {vf}")
                continue
            ok, out = _run(["helm", "template", "check", str(chart), "-f", str(values_path)], str(root))
            if not ok:
                failures.append(f"{name}: helm template with {vf} failed\n{out}")

    if failures:
        _finish(False, "FAIL:\n" + "\n\n".join(failures), start)
    _finish(True, f"PASS: {len(charts)} chart(s) linted", start)


if __name__ == "__main__":
    main()

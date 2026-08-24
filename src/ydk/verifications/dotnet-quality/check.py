#!/usr/bin/env python3
"""Verification plugin: dotnet-quality bundle.

Thin bundle that runs the dotnet-build and dotnet-format verification
plugins (NOT dotnet-test), mirroring how python-quality bundles ruff +
ty. Each sub-plugin is invoked as its own subprocess with the same JSON
context on stdin, matching how ydk's own verifier would run any plugin
-- no cross-plugin imports.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

VERIFICATIONS = ["dotnet-build", "dotnet-format"]


def _run_sub_check(name: str, context: dict) -> dict:
    """Subprocess-invoke sibling plugin ``name``'s check.py, returning its parsed result."""
    script = Path(__file__).resolve().parent.parent / name / "check.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(context),
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        stderr = proc.stderr.strip()
        detail = f"\n{stderr}" if stderr else ""
        return {
            "name": name,
            "passed": False,
            "output": f"{name} produced no valid JSON output (exit {proc.returncode}){detail}",
            "duration_seconds": 0.0,
            "detail": None,
        }


def main() -> None:
    """Run the dotnet-quality verification check."""
    context = json.loads(sys.stdin.read())
    start = time.time()

    results: dict[str, dict] = {}
    for name in VERIFICATIONS:
        results[name] = _run_sub_check(name, context)

    passed = all(result.get("passed") for result in results.values())

    output = "\n".join(f"[{name}] {results[name].get('output', '')}" for name in VERIFICATIONS)

    result = {
        "name": "dotnet-quality",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"checks": VERIFICATIONS, "results": results},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

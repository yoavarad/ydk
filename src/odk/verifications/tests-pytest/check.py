#!/usr/bin/env python3
"""Verification plugin: pytest test runner."""

import json
import re
import subprocess
import sys
import time
from pathlib import Path


def _discover_test_dir(project_root: str) -> str:
    """Discover the test directory that exists in the project."""
    root = Path(project_root)
    for d in ["tests", "test"]:
        if (root / d).is_dir():
            return d
    return "tests"


def _find_test_files(project_root: str, test_dir: str, changed_files: list[str]) -> list[str]:
    """Map changed source files to their corresponding test files.

    Pattern: app/core/services/foo_service/service.py -> tests/unit/core/services/test_foo_service.py
    Also includes any changed files that are already test files.
    """
    root = Path(project_root)
    test_files: list[str] = []

    for f in changed_files:
        # If it's already a test file, include directly
        if f.startswith(f"{test_dir}/") or f.startswith("test_"):
            if (root / f).exists():
                test_files.append(f)
            continue

        # Map source file to test file patterns
        p = Path(f)
        parts = list(p.parts)

        # app/core/services/foo_service/service.py -> test_foo_service_service.py
        # app/core/services/foo_service.py -> test_foo_service.py
        if "services" in parts:
            svc_idx = parts.index("services")
            # Get everything after "services"
            svc_parts = parts[svc_idx + 1 :]
            if svc_parts:
                if svc_parts[-1] == "service.py" and len(svc_parts) > 1:
                    # foo_service/service.py -> test_foo_service.py
                    test_name = f"test_{svc_parts[0]}.py"
                else:
                    # foo_service.py -> test_foo_service.py
                    test_name = f"test_{svc_parts[-1]}"
                    if not test_name.startswith("test_"):
                        test_name = f"test_{svc_parts[-1]}"

                # Search for matching test files
                for test_sub in [f"{test_dir}/unit/core/services", f"{test_dir}/unit", f"{test_dir}"]:
                    candidate = root / test_sub / test_name
                    if candidate.exists():
                        test_files.append(str(candidate.relative_to(root)))
                        break

    return test_files


def main() -> None:
    """Run the tests-pytest verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    config = context.get("config", {})
    level = config.get("level", "all")
    start = time.time()

    test_dir = _discover_test_dir(project_root)

    # Scope to changed files when available
    changed_files = context.get("changed_files")
    if changed_files:
        scoped_tests = _find_test_files(project_root, test_dir, changed_files)
        if scoped_tests:
            cmd = ["pytest", *scoped_tests, "-v", "--tb=short"]
        else:
            # No matching test files found — pass (nothing to test for these files)
            check_result = {
                "name": "tests-scoped",
                "passed": True,
                "output": "No test files match changed source files — skipped",
                "duration_seconds": round(time.time() - start, 1),
                "detail": {"level": "scoped", "changed_files": changed_files},
            }
            json.dump(check_result, sys.stdout)
            sys.exit(0)
            return
    elif level == "unit":
        cmd = ["pytest", f"{test_dir}/unit/", "-v", "--tb=short"]
    elif level == "integration":
        cmd = ["pytest", f"{test_dir}/integration/", "-v", "--tb=short"]
    elif level == "e2e":
        cmd = ["pytest", f"{test_dir}/e2e/", "-v", "--tb=short"]
    else:
        cmd = ["pytest", f"{test_dir}/", "-v", "--tb=short"]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=project_root,
        timeout=300,
    )
    output = result.stdout
    if result.stderr:
        output += "\n" + result.stderr

    # Parse test count from output
    test_count = None
    for line in output.splitlines():
        if "passed" in line:
            match = re.search(r"(\d+) passed", line)
            if match:
                test_count = int(match.group(1))

    passed = result.returncode == 0
    detail: dict[str, object] = {"level": level}
    if test_count is not None:
        detail["test_count"] = test_count

    check_name = f"tests-{level}" if level != "all" else "tests"
    check_result = {
        "name": check_name,
        "passed": passed,
        "output": output.strip(),
        "duration_seconds": round(time.time() - start, 1),
        "detail": detail,
    }
    json.dump(check_result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

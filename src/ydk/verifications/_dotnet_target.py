"""Shared .NET target discovery for the dotnet-build, dotnet-format and dotnet-test plugins.

Verification plugins run as subprocesses, so each plugin's ``check.py`` puts this
directory on ``sys.path`` and imports this module. Stdlib only.
"""

import re
import subprocess
from pathlib import Path

EXCLUDED_DIR_PARTS = frozenset({"bin", "obj", ".git", ".ydk", ".vs", "node_modules", "third_party"})
TEST_PROJECT_MARKERS = ("Test", "Tests")
SLNX_MIN_SDK = (9, 0, 200)


def configured_target(context: dict) -> str | None:
    """Return ``verification.dotnet.target`` from the plugin context, resolved against project_root."""
    target = ((context.get("config") or {}).get("dotnet") or {}).get("target")
    if not target:
        return None
    return str((Path(context["project_root"]) / target).resolve()) if not Path(target).is_absolute() else target


def target_problem(target: str) -> str | None:
    """Explain why a configured target is unusable, or None when it is a .sln/.slnx/.csproj file."""
    path = Path(target)
    if not path.exists():
        return f"verification.dotnet.target does not exist: {target}"
    if not path.is_file() or path.suffix.lower() not in (".sln", ".slnx", ".csproj"):
        return f"verification.dotnet.target must be a .sln, .slnx or .csproj file: {target}"
    return None


def sdk_supports_slnx(dotnet_bin: str, project_root: str) -> bool:
    """Return True when the SDK resolved from ``project_root`` can build ``.slnx`` (>= 9.0.200).

    Runs with ``cwd=project_root`` because a ``global.json`` there can pin the SDK.
    """
    try:
        result = subprocess.run(
            [dotnet_bin, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=project_root,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", result.stdout.strip())
    if match is None:
        return False
    return tuple(int(g) for g in match.groups()) >= SLNX_MIN_SDK


def _candidates(root: Path, pattern: str) -> list[Path]:
    """Files matching ``pattern`` under ``root`` outside excluded dirs, shallowest first then by path."""
    found = [p for p in root.rglob(pattern) if not EXCLUDED_DIR_PARTS & set(p.relative_to(root).parts)]
    return sorted(found, key=lambda p: (len(p.relative_to(root).parts), str(p)))


def find_targets(project_root: str, dotnet_bin: str, *, test_only: bool = False) -> list[str]:
    """Discover build targets: shallowest .sln, else shallowest .slnx (SDK permitting), else all .csproj.

    With ``test_only`` the .csproj fallback keeps only projects whose stem contains a test marker.
    """
    root = Path(project_root)
    slns = _candidates(root, "*.sln")
    if slns:
        return [str(slns[0])]
    slnxs = _candidates(root, "*.slnx")
    if slnxs and sdk_supports_slnx(dotnet_bin, project_root):
        return [str(slnxs[0])]
    projects = _candidates(root, "*.csproj")
    if test_only:
        projects = [p for p in projects if any(m in p.stem for m in TEST_PROJECT_MARKERS)]
    return sorted(str(p) for p in projects)

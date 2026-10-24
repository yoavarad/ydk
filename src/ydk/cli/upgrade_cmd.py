"""ydk upgrade — upgrade the CLI via uv tool, then re-sync bundled skills in a new process."""

from __future__ import annotations

import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import typer

REPO_URL = "git+https://github.com/yoavarad/ydk"


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    except OSError as exc:
        return subprocess.CompletedProcess(cmd, 127, "", f"cannot run {cmd[0]}: {exc}")


def _is_editable() -> bool:
    """True when ydk is installed in editable/dev mode (PEP 610 direct_url.json)."""
    try:
        raw = importlib.metadata.distribution("ydk").read_text("direct_url.json")
    except importlib.metadata.PackageNotFoundError:
        return False
    if not raw:
        return False
    try:
        return bool(json.loads(raw).get("dir_info", {}).get("editable"))
    except ValueError:
        return False


def _tool_binary() -> str:
    """Path to the uv-tool-installed ydk (via `uv tool dir --bin`); falls back to PATH lookup."""
    out = _run(["uv", "tool", "dir", "--bin"])
    bin_dir = out.stdout.strip()
    if out.returncode == 0 and bin_dir:
        for name in ("ydk.exe", "ydk"):
            candidate = Path(bin_dir) / name
            if candidate.is_file():
                return str(candidate)
    return shutil.which("ydk") or "ydk"


def _tool_version() -> str:
    """Version of the uv-tool-installed ydk, read from `uv tool list` (fresh process)."""
    out = _run(["uv", "tool", "list"]).stdout
    match = re.search(r"^ydk v?(\S+)", out, re.MULTILINE)
    return match.group(1) if match else "unknown"


def upgrade_command(
    version: str | None = typer.Option(None, "--version", help="Pin to release X.Y.Z (installs tag vX.Y.Z)"),
) -> None:
    """Upgrade the ydk CLI via uv tool, then run `ydk skills sync` with the new binary."""
    if _is_editable():
        typer.echo(
            "Editable/dev install detected; refusing to upgrade. "
            "Update the checkout (git pull) and run 'uv sync' instead.",
            err=True,
        )
        raise typer.Exit(code=1)
    old = importlib.metadata.version("ydk")
    if version is not None:
        if not version.removeprefix("v"):
            typer.echo("--version must not be empty", err=True)
            raise typer.Exit(code=2)
        cmd = ["uv", "tool", "install", "--force", f"{REPO_URL}@v{version.removeprefix('v')}"]
    else:
        cmd = ["uv", "tool", "upgrade", "ydk"]
    result = _run(cmd)
    if result.returncode != 0:
        typer.echo(f"{' '.join(cmd)} failed:\n{result.stderr or result.stdout}", err=True)
        if sys.platform == "win32":
            typer.echo(
                "If ydk.exe is locked by this running process, run "
                f"'{' '.join(cmd)}' from a shell where ydk is not running, then 'ydk skills sync'.",
                err=True,
            )
        raise typer.Exit(code=1)
    new = _tool_version()
    typer.echo(f"ydk {old} -> {new}")
    binary = _tool_binary()
    sync = _run([binary, "skills", "sync"])
    if sync.returncode != 0:
        typer.echo(f"skills sync failed:\n{sync.stderr or sync.stdout}", err=True)
        raise typer.Exit(code=1)
    typer.echo(sync.stdout.rstrip())

"""CLI commands invoked by generated git hooks (`ydk hooks ...`).

These replace the old shell-script logic that shelled out to `"$PY" -m ...`
after resolving a python interpreter at hook-run time — resolution that
silently failed on Windows `uv tool install` setups with no project `.venv`
(see GitHub issue #264). Running through the `ydk` entry point instead means
no interpreter resolution is needed at all: `ydk` is already resolved.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import typer

from ydk.cli.verify_cmd import run as verify_run
from ydk.hooks.commit_msg import VALID_TYPES, validate_commit_message

hooks_app = typer.Typer(name="hooks", help="Commands invoked by git hooks")

VERIFIED_FLAG = Path(".ydk/.verified")
VERIFIED_TTL_SECONDS = 300


@hooks_app.command("commit-msg")
def commit_msg(file: str = typer.Argument(..., help="Path to the commit message file")) -> None:
    """Validate a commit message file against conventional-commit format (git commit-msg hook)."""
    with open(file) as fh:
        message = fh.read()

    if not validate_commit_message(message):
        print(
            "commit-msg hook: message does not follow conventional commit format.\n"
            "Expected: type(scope): description  or  type: description\n"
            f"Valid types: {', '.join(sorted(VALID_TYPES))}",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)


@hooks_app.command("pre-push")
def pre_push() -> None:
    """Run pre-push verification (git pre-push hook).

    Honors the `.ydk/.verified` flag written by `ydk task done`: if it was
    written within the last `VERIFIED_TTL_SECONDS`, verification already ran
    recently and is skipped. Otherwise the flag (if present and stale) is
    removed and verification runs, propagating its exit code.
    """
    if VERIFIED_FLAG.is_file():
        try:
            verified_ts = float(VERIFIED_FLAG.read_text().strip())
        except (OSError, ValueError):
            verified_ts = None
        VERIFIED_FLAG.unlink(missing_ok=True)
        if verified_ts is not None and (time.time() - verified_ts) <= VERIFIED_TTL_SECONDS:
            print("Pre-push: skipping verification (ydk task done verified recently)")
            raise typer.Exit(code=0)

    try:
        verify_run(
            name=None,
            trigger="pre-push",
            auto_fix=False,
            no_cache=False,
            retry=None,
            repair=False,
            save_proof=False,
            task_id=None,
            pr=None,
            capture=False,
        )
    except typer.Exit:
        raise
    else:
        # verify_run always raises typer.Exit(0/1) based on report.all_passed
        # (see ydk.cli.verify_cmd.run). If it ever returns normally instead,
        # treat that as a failure rather than silently exiting 0.
        raise typer.Exit(code=1)

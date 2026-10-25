"""ydk release — cut a release branch: bump, lock, changelog, commit, open PR (no tag)."""

from __future__ import annotations

import enum
import os
import re
import shutil
import subprocess
from typing import Annotated

import typer

RELEASE_FILES = frozenset({"pyproject.toml", "uv.lock", "CHANGELOG.md"})


class Increment(enum.StrEnum):
    """Commitizen ``--increment`` choices."""

    MAJOR = "MAJOR"
    MINOR = "MINOR"
    PATCH = "PATCH"


def _proc(cmd: list[str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run *cmd* with UV_NO_SYNC so hooks never re-sync (and rebuild) the running ydk."""
    env = {**os.environ, "UV_NO_SYNC": "1"}
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", input=stdin, env=env)


def _rc(cmd: list[str]) -> int:
    """Run *cmd* and return its exit code without raising."""
    return _proc(cmd).returncode


def _run(cmd: list[str], *, stdin: str | None = None) -> str:
    """Run *cmd*, returning stdout; exit 1 with stderr on failure."""
    proc = _proc(cmd, stdin)
    if proc.returncode != 0:
        typer.echo(f"Command failed: {' '.join(cmd)}\n{(proc.stderr or proc.stdout).strip()}", err=True)
        raise typer.Exit(1)
    return proc.stdout


def _refuse(message: str) -> None:
    typer.echo(f"Refusing to release: {message}", err=True)
    raise typer.Exit(1)


def _preflight(dry_run: bool) -> None:
    """Refuse up front if a required executable is missing (gh is only needed for a real release)."""
    for tool in ("git", "cz") if dry_run else ("git", "cz", "gh"):
        if shutil.which(tool) is None:
            _refuse(f"required tool '{tool}' not found on PATH; install it and retry")


def changelog_section(changelog: str) -> str:
    """Return the body of the newest ``## vX.Y.Z`` section, without its heading."""
    match = re.search(r"^## .*?$\n(.*?)(?=^## |\Z)", changelog, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else changelog.strip()


def render_pr_body(version: str, section: str, get_next_cmd: str = "cz bump --get-next") -> str:
    """Fixed release PR body; satisfies the pr-body-validation plugin."""
    return f"""## Summary

Release v{version}: bumps `pyproject.toml`, refreshes `uv.lock`, and prepends this section to `CHANGELOG.md`.

{section}

## Test Plan

- [ ] CI passes on `release/v{version}`
- [ ] `CHANGELOG.md`, `pyproject.toml`, and `uv.lock` are the only files changed
- [ ] Tag `v{version}` is created on merge, not on this branch

```console
$ {get_next_cmd}
{version}
```
"""


def release_command(
    increment: Annotated[Increment | None, typer.Option("--increment", help="Force MAJOR, MINOR, or PATCH")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print version, branch, and PR body only")] = False,
) -> None:
    """Branch release/vX.Y.Z from main, run cz bump (no tag), push, and open the release PR."""
    _preflight(dry_run)
    start = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if start == "HEAD":
        start = _run(["git", "rev-parse", "HEAD"]).strip()
    if not dry_run and _run(["git", "status", "--porcelain", "--untracked-files=no"]).strip():
        _refuse("working tree is not clean")
    state = _State(start)
    try:
        url = _release(state, increment, dry_run)
    except BaseException:
        _rollback(state)
        raise
    if url is not None:
        typer.echo(url)


class _State:
    """Mutable progress of a release run, used for rollback."""

    def __init__(self, start: str) -> None:
        self.start = start
        self.moved = False
        self.branch_created = False
        self.push_attempted = False
        self.version = ""
        self.release_branch = ""


def _release(state: _State, increment: Increment | None, dry_run: bool) -> str | None:
    _run(["git", "fetch", "origin", "main"])
    if _run(["git", "rev-parse", "HEAD"]).strip() != _run(["git", "rev-parse", "origin/main"]).strip():
        if dry_run:
            typer.echo(f"Note: previewing from {state.start}, not origin/main; a real release is based on origin/main.")
        else:
            typer.echo("Basing release on origin/main.")
            state.moved = True
            _run(["git", "checkout", "--detach", "origin/main"])

    inc = ["--increment", increment.value] if increment else []
    get_next = ["cz", "bump", "--get-next", *inc]
    version = _run(get_next).strip()
    release_branch = f"release/v{version}"
    preview = _run(["cz", "changelog", "--dry-run", "--unreleased-version", f"v{version}"])
    body = render_pr_body(version, changelog_section(preview), " ".join(get_next))

    typer.echo(f"Version: {version}")
    typer.echo(f"Branch: {release_branch}")
    if dry_run:
        typer.echo(f"PR title: release: v{version}\n\n{body}")
        return None

    state.version = version
    state.release_branch = release_branch
    leftovers = [
        (["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{release_branch}"], f"local branch {release_branch}"),
        (["git", "rev-parse", "--verify", "--quiet", f"refs/tags/v{version}"], f"local tag v{version}"),
    ]
    found = [name for cmd, name in leftovers if _rc(cmd) == 0]
    remote_rc = _rc(["git", "ls-remote", "--exit-code", "--heads", "origin", release_branch])
    if remote_rc not in (0, 2):
        _refuse(f"could not check origin for {release_branch} (git ls-remote exit {remote_rc})")
    if remote_rc == 0:
        found.append(f"remote branch {release_branch}")
    if found:
        _refuse(
            f"leftovers from a previous attempt: {', '.join(found)}. Clean up with: "
            f"git branch -D {release_branch}; git tag -d v{version}; git push origin --delete {release_branch} "
            "(only the ones that exist)"
        )

    _run(["git", "checkout", "-b", release_branch])
    state.branch_created = True
    return _bump_push_and_open_pr(state, inc, body)


def _rollback(state: _State) -> None:
    """Best-effort undo of a failed release; report commands that need manual cleanup."""
    steps: list[list[str]] = []
    if state.branch_created:
        steps.append(["git", "reset", "--hard"])
    if state.moved or state.branch_created:
        steps.append(["git", "checkout", state.start])
    if state.branch_created:
        steps.append(["git", "branch", "-D", state.release_branch])
    failed = [" ".join(cmd) for cmd in steps if _rc(cmd) != 0]
    if state.branch_created:
        tag = ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/v{state.version}"]
        delete_tag = ["git", "tag", "-d", f"v{state.version}"]
        if _rc(tag) == 0 and _rc(delete_tag) != 0:
            failed.append(" ".join(delete_tag))
    remote_check = ["git", "ls-remote", "--exit-code", "--heads", "origin", state.release_branch]
    if state.push_attempted and _rc(remote_check) == 0:
        delete_remote = ["git", "push", "origin", "--delete", state.release_branch]
        if _rc(delete_remote) != 0:
            failed.append(" ".join(delete_remote))
    typer.echo(f"Release aborted; rolled back to {state.start}.", err=True)
    if failed:
        typer.echo(f"Rollback commands that failed (run manually): {'; '.join(failed)}", err=True)


def _bump_push_and_open_pr(state: _State, inc: list[str], body: str) -> str:
    """Run the bump on the release branch, verify the commit, push, and open the PR; return its URL."""
    version, release_branch = state.version, state.release_branch
    _run(["cz", "bump", "--yes", *inc])
    commits = _run(["git", "rev-list", "--count", "origin/main..HEAD"]).strip()
    files = {f.strip() for f in _run(["git", "show", "--name-only", "--format=", "HEAD"]).splitlines() if f.strip()}
    if commits != "1" or files != RELEASE_FILES:
        _refuse(
            f"expected one commit touching {', '.join(sorted(RELEASE_FILES))}; "
            f"got {commits} commit(s) touching {', '.join(sorted(files)) or 'nothing'}"
        )
    state.push_attempted = True
    _run(["git", "push", "-u", "origin", release_branch])
    out = _run(
        [
            "gh",
            "pr",
            "create",
            "--base",
            "main",
            "--head",
            release_branch,
            "--title",
            f"release: v{version}",
            "--body-file",
            "-",
        ],
        stdin=body,
    )
    return out.strip().splitlines()[-1] if out.strip() else ""

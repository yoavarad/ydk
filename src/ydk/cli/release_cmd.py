"""ydk release — cut a release branch: bump, lock, changelog, commit, open PR (no tag)."""

from __future__ import annotations

import enum
import re
import subprocess
from typing import Annotated

import typer

RELEASE_FILES = frozenset({"pyproject.toml", "uv.lock", "CHANGELOG.md"})


class Increment(enum.StrEnum):
    """Commitizen ``--increment`` choices."""

    MAJOR = "MAJOR"
    MINOR = "MINOR"
    PATCH = "PATCH"


def _run(cmd: list[str], *, stdin: str | None = None) -> str:
    """Run *cmd*, returning stdout; exit 1 with stderr on failure."""
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", input=stdin)
    if proc.returncode != 0:
        typer.echo(f"Command failed: {' '.join(cmd)}\n{(proc.stderr or proc.stdout).strip()}", err=True)
        raise typer.Exit(1)
    return proc.stdout


def _refuse(message: str) -> None:
    typer.echo(f"Refusing to release: {message}", err=True)
    raise typer.Exit(1)


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
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if branch != "main":
        _refuse(f"on branch '{branch}', not main")
    if _run(["git", "status", "--porcelain", "--untracked-files=no"]).strip():
        _refuse("working tree is not clean")
    _run(["git", "fetch", "origin", "main"])
    if _run(["git", "rev-parse", "HEAD"]).strip() != _run(["git", "rev-parse", "origin/main"]).strip():
        _refuse("local main is not up to date with origin/main")

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
        return

    _run(["git", "checkout", "-b", release_branch])
    try:
        url = _bump_push_and_open_pr(version, release_branch, inc, body)
    except typer.Exit:
        typer.echo(
            f"Release aborted on {release_branch}. To retry: git checkout main && "
            f"git branch -D {release_branch} && git tag -d v{version} (if it exists); "
            f"delete origin/{release_branch} too if it was pushed.",
            err=True,
        )
        raise
    typer.echo(url)


def _bump_push_and_open_pr(version: str, release_branch: str, inc: list[str], body: str) -> str:
    """Run the bump on the release branch, verify the commit, push, and open the PR; return its URL."""
    _run(["cz", "bump", "--yes", *inc])
    commits = _run(["git", "rev-list", "--count", "origin/main..HEAD"]).strip()
    files = {f.strip() for f in _run(["git", "show", "--name-only", "--format=", "HEAD"]).splitlines() if f.strip()}
    if commits != "1" or files != RELEASE_FILES:
        _refuse(
            f"expected one commit touching {', '.join(sorted(RELEASE_FILES))}; "
            f"got {commits} commit(s) touching {', '.join(sorted(files)) or 'nothing'}"
        )
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

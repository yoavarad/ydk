"""odk watch — GitHub PR comment watcher with Claude Code session resume."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from odk.core.watch import WatchManager

watch_app = typer.Typer(name="watch", help="GitHub PR comment watcher")


@watch_app.command("install")
def install() -> None:
    """Install macOS launchd plist for 30-second polling."""
    mgr = WatchManager(Path("."))
    plist_content = mgr.generate_plist()
    plist_path = mgr.plist_path()

    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(plist_content, encoding="utf-8")

    # Load the agent
    result = subprocess.run(
        ["launchctl", "load", str(plist_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        typer.echo(f"Warning: launchctl load failed: {result.stderr.strip()}", err=True)
    else:
        typer.echo(f"Watcher installed: {plist_path}")
        typer.echo("Polling every 30 seconds. Use 'odk watch status' to verify.")


@watch_app.command("uninstall")
def uninstall() -> None:
    """Remove the launchd plist and stop the watcher."""
    mgr = WatchManager(Path("."))
    plist_path = mgr.plist_path()

    if not plist_path.is_file():
        typer.echo("No watcher installed for this project.")
        raise typer.Exit(code=1)

    # Unload the agent
    subprocess.run(
        ["launchctl", "unload", str(plist_path)],
        capture_output=True,
        text=True,
    )

    plist_path.unlink()
    typer.echo(f"Watcher uninstalled: {plist_path}")


@watch_app.command("poll")
def poll() -> None:
    """Check for new PR review comments and trigger agent sessions."""
    mgr = WatchManager(Path("."))

    if not mgr.acquire_lock():
        typer.echo("Another poll is already running. Skipping.")
        return

    try:
        results = mgr.poll()

        if not results:
            typer.echo("No new review comments found.")
            return

        for r in results:
            comment_summary = "\n".join(
                f"  - {c['path']}:{c.get('line', '?')}: {c['body'][:200]}" for c in r["comments"]
            )
            message = (
                f"New review comments on PR #{r['pr_number']} for task {r['task_id']}:\n"
                f"{comment_summary}\n\n"
                "Address each comment. For EACH comment:\n"
                "1. Make the requested change (or explain why no change is needed)\n"
                "2. Run verification: ruff check, pytest\n"
                "3. Commit and push to the same branch\n"
                "4. Post a reply comment on the PR using this EXACT format:\n"
                "\n"
                "gh pr comment {pr_number} --body '<!-- odk-agent-reply -->\n"
                "> <quoted original comment text>\n"
                "\n"
                "**Addressed.** <what was changed or why no change needed>\n"
                "\n"
                "Changed files:\n"
                "- `path/to/file.py` (line N: description)\n"
                "\n"
                "<details>\n"
                "<summary>Verification</summary>\n"
                "\n"
                "```\n"
                "<paste actual ruff check + pytest output>\n"
                "```\n"
                "\n"
                "</details>\n"
                "\n"
                "Pushed: `<commit-hash>` on `<branch>`\n"
                "'\n"
                "\n"
                "IMPORTANT: Every reply MUST start with <!-- odk-agent-reply --> on the first line. "
                "This prevents the watcher from re-triggering on your own replies."
            ).format(pr_number=r["pr_number"])
            mgr.trigger_agent(r["session_id"], str(Path(".").resolve()), message)
            typer.echo(f"Triggered session {r['session_id']} for task {r['task_id']} ({len(r['comments'])} comments)")
    finally:
        mgr.release_lock()


@watch_app.command("status")
def status() -> None:
    """Show watcher status: installed?, last poll, active sessions."""
    mgr = WatchManager(Path("."))

    # Check if plist is installed
    plist_path = mgr.plist_path()
    if plist_path.is_file():
        typer.echo(f"Watcher: INSTALLED ({plist_path})")
    else:
        typer.echo("Watcher: NOT INSTALLED")

    # Last poll time
    last_poll = mgr.last_poll_time()
    if last_poll:
        typer.echo(f"Last poll: {last_poll}")
    else:
        typer.echo("Last poll: never")

    # Active sessions
    sessions = mgr.get_active_sessions()
    if not sessions:
        typer.echo("Active sessions: none")
        return

    typer.echo(f"\nSessions ({len(sessions)}):")
    for task_id, info in sessions.items():
        pr = info.get("pr_number", "no PR")
        session = info.get("session_id", "?")[:12]
        task_status = info.get("status", "?")
        typer.echo(f"  {task_id}: PR #{pr}  session={session}...  status={task_status}")

"""CLI commands for the visual companion."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from odk.cli._helpers import format_or_echo
from odk.core.visual import VisualEngine
from odk.output.console import console

visual_app = typer.Typer(name="visual", help="Browser-based design annotation companion")


def _make_engine(project_dir: Path | None = None) -> VisualEngine:
    """Build a VisualEngine for the given project directory."""
    return VisualEngine(project_dir=project_dir)


@visual_app.command("start")
def start(
    project_dir: Path = typer.Option(Path("."), "--project-dir", "-p", help="Project root directory"),  # noqa: B008
) -> None:
    """Start a new visual companion session."""
    engine = _make_engine(project_dir)
    session = engine.start_session()
    console.print(f"[green]Session started:[/green] {session.id}")
    console.print(f"  URL:         {session.url}")
    console.print(f"  Content dir: {session.content_dir}")
    console.print(f"  State dir:   {session.state_dir}")
    console.print(f"  PID:         {session.pid}")


@visual_app.command("stop")
def stop(
    session_id: str = typer.Argument(..., help="Session ID to stop"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", "-p", help="Project root directory"),  # noqa: B008
) -> None:
    """Stop a running visual companion session."""
    engine = _make_engine(project_dir)
    try:
        engine.stop_session(session_id)
        console.print(f"[green]Session stopped:[/green] {session_id}")
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None


@visual_app.command("push")
def push(
    content: str = typer.Argument(..., help="HTML content string or file path"),
    filename: str = typer.Option("index.html", "--filename", "-f", help="Filename in content dir"),
    session_id: str = typer.Option("", "--session-id", "-s", help="Session ID (uses latest if empty)"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", "-p", help="Project root directory"),  # noqa: B008
) -> None:
    """Push content to a visual companion session."""
    engine = _make_engine(project_dir)

    sid = session_id or _latest_session_id(engine)
    if not sid:
        console.print("[red]No active sessions found. Start one with: odk visual start[/red]")
        raise typer.Exit(code=1)

    content_str = content
    content_path = Path(content)
    if content_path.exists() and content_path.is_file():
        content_str = content_path.read_text()

    try:
        path = engine.push_content(sid, content_str, filename)
        console.print(f"[green]Content pushed:[/green] {path}")
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None


@visual_app.command("feedback")
def feedback(
    ctx: typer.Context,
    session_id: str = typer.Option("", "--session-id", "-s", help="Session ID (uses latest if empty)"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", "-p", help="Project root directory"),  # noqa: B008
) -> None:
    """Read feedback events from a visual companion session."""
    engine = _make_engine(project_dir)

    sid = session_id or _latest_session_id(engine)
    if not sid:
        console.print("[yellow]No active sessions found.[/yellow]")
        return

    try:
        events = engine.read_feedback(sid)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    if not events:
        console.print("[yellow]No feedback events yet.[/yellow]")
        return

    data = [e.model_dump() for e in events]
    if format_or_echo(ctx, data):
        return

    for event in events:
        icons = {
            "selection": "[cyan]SEL[/cyan]",
            "element_annotation": "[blue]ELM[/blue]",
            "rectangle_annotation": "[magenta]RCT[/magenta]",
        }
        icon = icons.get(event.type, "???")
        comment = getattr(event, "comment", None) or getattr(event, "choiceText", None) or ""
        console.print(f"  {icon}  {comment[:80]}")


@visual_app.command("screenshot")
def screenshot(
    url: str = typer.Option("", "--url", "-u", help="URL to capture (defaults to session URL)"),
    output: Path = typer.Option(Path("screenshot.png"), "--output", "-o", help="Output file path"),  # noqa: B008
    session_id: str = typer.Option("", "--session-id", "-s", help="Session ID"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", "-p", help="Project root directory"),  # noqa: B008
) -> None:
    """Capture a screenshot of a visual companion page."""
    engine = _make_engine(project_dir)

    sid = session_id or _latest_session_id(engine)
    if not sid:
        console.print("[red]No active sessions found.[/red]")
        raise typer.Exit(code=1)

    session = engine.get_session(sid)
    if session is None:
        console.print(f"[red]Session not found: {sid}[/red]")
        raise typer.Exit(code=1)

    target_url = url or session.url
    try:
        result_path = engine.capture_screenshot(sid, target_url, output)
        console.print(f"[green]Screenshot saved:[/green] {result_path}")
    except (subprocess.CalledProcessError, OSError) as exc:
        console.print(f"[red]Screenshot failed: {exc}[/red]")
        raise typer.Exit(code=1) from None


@visual_app.command("list")
def list_sessions(
    ctx: typer.Context,
    project_dir: Path = typer.Option(Path("."), "--project-dir", "-p", help="Project root directory"),  # noqa: B008
) -> None:
    """List all visual companion sessions."""
    engine = _make_engine(project_dir)
    sessions = engine.list_sessions()

    if not sessions:
        console.print("[yellow]No visual sessions found.[/yellow]")
        return

    data = [s.model_dump() for s in sessions]
    if format_or_echo(ctx, data):
        return

    for s in sessions:
        status_style = "[green]" if s.status.value == "running" else "[dim]"
        console.print(f"  {status_style}{s.status.value}[/] {s.id}  port={s.port}  pid={s.pid}")


@visual_app.command("record")
def record(
    url: str = typer.Option(..., "--url", "-u", help="URL to record"),
    actions_file: Path | None = typer.Option(None, "--actions-file", "-a", help="JSON actions list"),  # noqa: B008
    output: Path = typer.Option(Path(".odk/proofs/latest"), "--output", "-o", help="Output dir for video"),  # noqa: B008
    wait_ms: int = typer.Option(3000, "--wait", help="Wait time in ms (used when no actions file)"),
) -> None:
    """Record a video of a page or browser flow using Playwright."""
    import json

    from odk.core.video_capture import VideoCapture

    vc = VideoCapture()
    try:
        if actions_file and actions_file.exists():
            actions = json.loads(actions_file.read_text())
            video_path = vc.record_session(url, actions, output)
        else:
            video_path = vc.record_page(url, output, wait_ms=wait_ms)
        console.print(f"[green]Video recorded:[/green] {video_path}")
    except ImportError:
        console.print("[red]Playwright not installed. Run: pip install playwright && playwright install[/red]")
        raise typer.Exit(code=1) from None
    except (FileNotFoundError, OSError) as exc:
        console.print(f"[red]Recording failed: {exc}[/red]")
        raise typer.Exit(code=1) from None


def _latest_session_id(engine: VisualEngine) -> str:
    """Return the ID of the most recently created session, or empty string."""
    sessions = engine.list_sessions()
    if not sessions:
        return ""
    return sessions[-1].id

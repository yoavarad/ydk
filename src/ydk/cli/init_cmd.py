"""ydk init — initialize .ydk/ in a project."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import typer

from ydk.core.config import init_config
from ydk.core.doctor import CheckSeverity, Doctor
from ydk.output.console import console


def _python_command() -> str:
    """Return a python invocation usable in generated hook commands.

    Prefers the interpreter currently running (always resolvable), falling
    back to a bare ``python`` on PATH. Avoids hardcoding ``python3``, which
    is often missing or an unusable stub on Windows.
    """
    return sys.executable or shutil.which("python") or "python"


def _make_executable(path: Path) -> None:
    """Set the executable bit on POSIX. No-op on Windows (no chmod bit there)."""
    if os.name != "nt":
        path.chmod(path.stat().st_mode | stat.S_IEXEC)


# ---------------------------------------------------------------------------
# GitHub templates
# ---------------------------------------------------------------------------

_ISSUE_TEMPLATE_TASK = """\
---
name: Task
about: Atomic work item for agent implementation
labels: task
---

**Story**: #
**Spec refs**:
**Dependencies**:

### Description


### Acceptance Criteria
- [ ]

### Test Strategy

"""

_ISSUE_TEMPLATE_STORY = """\
---
name: Story
about: Deliverable piece of user value
labels: story
---

**Epic**: #
**Spec refs**:

### Acceptance Criteria
- [ ]

"""

_ISSUE_TEMPLATE_EPIC = """\
---
name: Epic
about: Large initiative grouping stories
labels: epic
---

**Release**:
**Spec refs**:

### Description

### Scope

"""

_PR_TEMPLATE = """\
## Changes


## Verification Proof

<!-- YDK fills this in automatically -->

## Spec refs


Closes #
"""


_REQUIRED_LABELS: list[tuple[str, str]] = [
    ("epic", "0052cc"),  # blue
    ("story", "2ea44f"),  # green
    ("task", "fbca04"),  # yellow
    ("blocked-by-code", "d73a4a"),  # red
    ("blocked-by-decision", "e99695"),  # orange
    ("in-progress", "6f42c1"),  # purple
]


def _create_github_labels() -> None:
    """Create required GitHub labels, skipping any that already exist."""
    for label_name, color in _REQUIRED_LABELS:
        subprocess.run(
            ["gh", "label", "create", label_name, "--color", color, "--force"],
            capture_output=True,
        )


def _install_github_templates() -> None:
    """Create .github/ with issue templates and PR template."""
    github_dir = Path(".github")
    issue_dir = github_dir / "ISSUE_TEMPLATE"
    issue_dir.mkdir(parents=True, exist_ok=True)

    (issue_dir / "task.md").write_text(_ISSUE_TEMPLATE_TASK, encoding="utf-8")
    (issue_dir / "story.md").write_text(_ISSUE_TEMPLATE_STORY, encoding="utf-8")
    (issue_dir / "epic.md").write_text(_ISSUE_TEMPLATE_EPIC, encoding="utf-8")
    (github_dir / "PULL_REQUEST_TEMPLATE.md").write_text(_PR_TEMPLATE, encoding="utf-8")


# ---------------------------------------------------------------------------
# Claude Code guard script (PreToolUse hook)
# ---------------------------------------------------------------------------

_GUARD_SCRIPT = '''\
#!/usr/bin/env python3
"""YDK unified guard hook — all guard checks in one script."""
import json, sys, threading
from pathlib import Path

# Read stdin (Claude Code pipes tool context as JSON).
# A POSIX-only readiness check on sys.stdin would raise on Windows, so a
# background thread with a join timeout is used instead — it works the
# same way on every platform and still fails open (allows the action) if
# no data shows up within the timeout.
def _read_stdin(timeout=0.5):
    box = {}
    def _reader():
        try:
            box["data"] = sys.stdin.read()
        except Exception:
            box["data"] = ""
    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None  # No data in time = allow
    return box.get("data", "")

raw = _read_stdin(0.5)
if raw is None:
    sys.exit(0)  # No data = allow

try:
    data = json.loads(raw)
except (json.JSONDecodeError, ValueError):
    sys.exit(0)  # Bad data = fail open

tool_name = data.get("tool_name", "")
tool_input = data.get("tool_input", {})
cwd = data.get("cwd", ".")
file_path = tool_input.get("file_path", "")
command = tool_input.get("command", "")

# Normalize file_path (remove cwd prefix)
if file_path.startswith(cwd):
    file_path = file_path[len(cwd):].lstrip("/")

root = Path(cwd)

# --- GUARD: no-manual-pr and no-direct-push ---
if tool_name == "Bash" and ("gh pr create" in command or "gh pr merge" in command):
    sys.stderr.write("BLOCKED: Use \'ydk task done\' to create PRs — it captures verification proof.\\n")
    sys.exit(2)
# git push is allowed — ydk task done needs it internally
# Only gh pr create is blocked (forces proof-based PRs)

# --- GUARD: no-proof-tamper ---
if tool_name in ("Edit", "Write") and ".ydk/proofs/" in file_path and "summary.md" not in file_path:
    sys.stderr.write("BLOCKED: Proof files are generated by \'ydk task done\'. Do not edit manually.\\n")
    sys.exit(2)

# --- GUARD: no-noqa ---
if tool_name in ("Edit", "Write"):
    new_content = tool_input.get("new_string", "") or tool_input.get("content", "")
    if new_content and not file_path.startswith("tests/"):
        for marker in ("# noqa", "# type: ignore", "# nosec"):
            if marker in new_content:
                sys.stderr.write(f"BLOCKED: \'{marker}\' not allowed. Fix the violation instead of suppressing it.\\n")
                sys.exit(2)

# --- GUARD: no-mock-internals ---
if tool_name in ("Edit", "Write") and file_path.startswith("tests/"):
    new_content = tool_input.get("new_string", "") or tool_input.get("content", "")
    if new_content:
        for pattern in (\'@patch("app.\', \'@patch("src.\', "@patch(\'app.", "@patch(\'src."):
            if pattern in new_content:
                sys.stderr.write("BLOCKED: Don\'t mock internal classes. Use fakes and DI overrides.\\n")
                sys.exit(2)

# --- GUARD: stage-gate ---
state_file = root / ".ydk" / "state.json"
if state_file.exists() and file_path:
    try:
        state = json.loads(state_file.read_text())
        stage = state.get("stage", "00")

        # Stage 01/02: block source file edits
        if stage in ("01", "02") and file_path.startswith(("src/", "app/", "tests/")):
            if not file_path.startswith(".ydk/"):
                sys.stderr.write(f"BLOCKED: Stage {stage} — cannot edit source files yet.\\n")
                sys.exit(2)
    except Exception:
        pass  # State unreadable = allow

sys.exit(0)  # All checks passed — allow
'''

# ---------------------------------------------------------------------------
# Git hooks
# ---------------------------------------------------------------------------


def _install_claude_hooks() -> None:
    """Create .claude/settings.json with guard hooks for real-time enforcement."""
    import json

    claude_dir = Path(".claude")
    claude_dir.mkdir(parents=True, exist_ok=True)

    # Install hook scripts
    hooks_dir = claude_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)

    # SubagentStop hook
    check_script = hooks_dir / "check-task-complete.sh"
    check_script.write_text(
        "#!/bin/bash\n"
        "# SubagentStop hook: blocks session end if a task is still in progress.\n"
        "# Exit 0 = allow (task was completed or never started)\n"
        "# Exit 2 = block (task started but not done — message fed back to agent)\n"
        "\n"
        'ACTIVE_TASK=".ydk/active-task.json"\n'
        "\n"
        'if [ ! -f "$ACTIVE_TASK" ]; then\n'
        "    exit 0\n"
        "fi\n"
        "\n"
        "TASK_ID=$(python3 -c \"import json; print(json.load(open('$ACTIVE_TASK'))['task_id'])\" 2>/dev/null)\n"
        "\n"
        'if [ -z "$TASK_ID" ]; then\n'
        "    exit 0\n"
        "fi\n"
        "\n"
        'echo "BLOCKED: Task $TASK_ID is still in progress."\n'
        'echo ""\n'
        'echo "You must complete the task before finishing:"\n'
        'echo "  1. Ensure all tests pass"\n'
        'echo "  2. Ensure lint is clean"\n'
        'echo "  3. Run: ydk task done $TASK_ID"\n'
        'echo ""\n'
        'echo "The session cannot end until the task is properly completed with a PR."\n'
        "exit 2\n"
    )
    if os.name != "nt":
        check_script.chmod(0o755)

    # Unified PreToolUse guard script
    guard_script = hooks_dir / "guard.py"
    guard_script.write_text(_GUARD_SCRIPT, encoding="utf-8")
    if os.name != "nt":
        guard_script.chmod(0o755)

    settings_path = claude_dir / "settings.json"

    settings = {
        "permissions": {
            "allow": [
                "Bash(*)",
                "Read(*)",
                "Edit(*)",
                "Write(*)",
                "Grep(*)",
                "Glob(*)",
            ],
        },
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Edit|Write|Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{_python_command()} .claude/hooks/guard.py",
                        }
                    ],
                },
            ],
        },
    }

    # bash/sh may not be resolvable on plain Windows (no Git Bash/WSL) —
    # skip wiring the SubagentStop hook rather than installing a command
    # that will fail every time it's invoked.
    if shutil.which("bash") is not None:
        settings["hooks"]["SubagentStop"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "bash .claude/hooks/check-task-complete.sh",
                    }
                ],
            },
        ]
    else:
        console.print(
            "[yellow]Warning: 'bash' not found on PATH — skipping SubagentStop hook "
            "(check-task-complete.sh) install.[/yellow]"
        )

    if settings_path.exists():
        existing = json.loads(settings_path.read_text())
        existing["hooks"] = settings["hooks"]
        existing["permissions"] = settings["permissions"]
        settings_path.write_text(json.dumps(existing, indent=2))
    else:
        settings_path.write_text(json.dumps(settings, indent=2))


def _install_hooks() -> None:
    """Create .ydk/hooks/ with pre-commit and pre-push scripts, set git config."""
    hooks_dir = Path(".ydk/hooks")
    hooks_dir.mkdir(parents=True, exist_ok=True)

    # Resolve a python command at hook-run time rather than baking in a
    # path — the hook script is checked into the repo and may run on a
    # different machine/PATH than the one that ran `ydk init`. Falls back
    # from python3 -> python since neither name is guaranteed present.
    _py_resolve = "PY=$(command -v python3 || command -v python || echo python3)\n"

    pre_commit = hooks_dir / "pre-commit"
    pre_commit.write_text("#!/bin/sh\nydk verify run --trigger pre-commit\n", encoding="utf-8")
    _make_executable(pre_commit)

    pre_push = hooks_dir / "pre-push"
    pre_push.write_text(
        "#!/bin/sh\n"
        "# Skip verification if ydk task done already ran it recently\n"
        + _py_resolve
        + 'VERIFIED_FLAG=".ydk/.verified"\n'
        'if [ -f "$VERIFIED_FLAG" ]; then\n'
        '  VERIFIED_TS=$(cat "$VERIFIED_FLAG")\n'
        '  NOW=$("$PY" -c "import time; print(time.time())")\n'
        "  AGE=$(\"$PY\" -c \"print(float('$NOW') - float('$VERIFIED_TS'))\")\n"
        '  EXPIRED=$("$PY" -c "print(1 if float(\'$AGE\') > 300 else 0)")\n'
        '  if [ "$EXPIRED" = "0" ]; then\n'
        '    echo "Pre-push: skipping verification (ydk task done verified recently)"\n'
        '    rm -f "$VERIFIED_FLAG"\n'
        "    exit 0\n"
        "  fi\n"
        '  rm -f "$VERIFIED_FLAG"\n'
        "fi\n"
        "ydk verify run --trigger pre-push\n"
    )
    _make_executable(pre_push)

    commit_msg = hooks_dir / "commit-msg"
    commit_msg.write_text(f'#!/bin/sh\n{_py_resolve}"$PY" -m ydk.hooks.commit_msg "$1"\n', encoding="utf-8")
    _make_executable(commit_msg)

    subprocess.run(
        ["git", "config", "core.hooksPath", ".ydk/hooks"],
        capture_output=True,
    )


def _install_spec_reviewers(config: object) -> None:
    """Copy built-in spec-reviewer YAMLs to ``.ydk/spec-reviewers/``."""
    from ydk.models.config import YdkConfig
    from ydk.spec_reviewers import REVIEWERS_DIR

    assert isinstance(config, YdkConfig)
    dest = Path(config.spec_check.reviewers_path)
    dest.mkdir(parents=True, exist_ok=True)
    # Also create custom/ subdirectory for user-defined reviewers
    (dest / "custom").mkdir(exist_ok=True)

    for yaml_file in sorted(REVIEWERS_DIR.glob("*.yaml")):
        target = dest / yaml_file.name
        if not target.exists():
            shutil.copy2(yaml_file, target)


def init_command(
    name: str = typer.Option(..., "--name", "-n", help="Project name"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing config"),
    remote: str = typer.Option("local", "--remote", "-r", help="Remote type: local, github, gitlab"),
    stack: str = typer.Option(
        "", "--stack", "-s", help="Technology stack: python-fastapi, python-cli, nextjs-fsd, terraform"
    ),
) -> None:
    """Initialize YDK in a project directory."""
    try:
        config = init_config(
            project_name=name,
            force=force,
            remote=remote if remote != "local" else None,
            stack=stack or None,
        )
    except FileExistsError:
        typer.echo("Error: .ydk/config.yaml already exists. Use --force to overwrite.", err=True)
        raise typer.Exit(code=1) from None

    # Create docs directories if they don't exist
    spec_dir = Path(config.project.spec_location)
    adrs_dir = Path(config.project.adrs_location)
    rules_file = Path("docs/project-rules.md")

    spec_dir.mkdir(parents=True, exist_ok=True)
    adrs_dir.mkdir(parents=True, exist_ok=True)
    if not rules_file.exists():
        rules_file.parent.mkdir(parents=True, exist_ok=True)
        rules_file.write_text("# Project Rules\n\nConventions, preferences, and domain knowledge.\n", encoding="utf-8")

    # Copy built-in spec-reviewers to project
    _install_spec_reviewers(config)

    # Install git hooks (with pre-push verified flag support)
    _install_hooks()

    # Install GitHub templates
    _install_github_templates()

    # Create required GitHub labels if remote is github
    if config.project.remote == "github":
        _create_github_labels()

    # Set initial state to stage 00 (setup)
    from ydk.core.state import ProjectState

    project_state = ProjectState(Path("."))
    project_state.update(stage="00")

    # Install Claude Code guard hooks
    _install_claude_hooks()

    console.print(f"[green]YDK initialized for project '{config.project.name}'[/green]\n")

    # Summary table
    from rich.table import Table

    schemas_dir = Path(config.components.schemas_path)
    schemas_count = len(list(schemas_dir.glob("*.yaml"))) if schemas_dir.is_dir() else 0

    hooks_enabled = (
        config.hooks.commit_msg_check or config.hooks.pre_push.spec_check or config.hooks.pre_push.task_check
    )

    table = Table(title="Project Summary")
    table.add_column("Setting", style="bold")
    table.add_column("Value")
    table.add_row("Project", config.project.name)
    table.add_row("Remote", config.project.remote)
    table.add_row("Stack", config.project.stack or "(none)")
    table.add_row("Hooks enabled", "yes" if hooks_enabled else "no")
    table.add_row("Schemas", str(schemas_count))
    console.print(table)
    console.print()

    # Run doctor
    console.print("[bold]Running health checks...[/bold]\n")
    doc = Doctor()
    results = doc.run_all()

    for r in results:
        icon = {
            CheckSeverity.ok: "[green]✓[/green]",
            CheckSeverity.warning: "[yellow]⚠[/yellow]",
            CheckSeverity.error: "[red]✗[/red]",
        }
        console.print(f"  {icon[r.severity]} {r.name}: {r.message}")

    ok_count = sum(1 for r in results if r.severity == CheckSeverity.ok)
    total = len(results)
    console.print(f"\n{ok_count}/{total} checks passed.")

    # Advance to stage 01 if schemas and pack are already installed
    schemas_dir = Path(config.components.schemas_path)
    packs_dir = Path(".ydk") / "ignition-packs"
    if (schemas_dir.is_dir() and list(schemas_dir.glob("*.yaml"))) and (
        packs_dir.is_dir() and list(packs_dir.iterdir())
    ):
        project_state.update(stage="01")

    # Offer catalog search for ignition packs
    # Skip in non-interactive mode (piped input, test runners, CI)
    import sys

    if sys.stdin.isatty():
        console.print()
        try:
            search_catalog = typer.confirm("Search catalog for an ignition pack?", default=False)
        except (EOFError, OSError):
            search_catalog = False
    else:
        search_catalog = False
    if search_catalog:
        from ydk.core.catalog import LocalCatalogBackend

        backend = LocalCatalogBackend()
        items = backend.search("ignition-pack", tags=["ignition-pack"])
        if items:
            console.print("\n[bold]Available ignition packs:[/bold]")
            for item in items:
                console.print(f"  - {item.name} v{item.version}  ({', '.join(item.tags)})")
            console.print("\nRun [bold]ydk catalog install <name>[/bold] to install one.")
        else:
            console.print("[yellow]No ignition packs found in catalog.[/yellow]")

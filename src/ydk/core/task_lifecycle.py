"""Task lifecycle orchestration.

Coordinates the full task flow: start -> plan -> progress -> block -> done.
Uses dependency injection for all collaborators.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from ydk.core.events import (
    EventBus,
    TaskBlockedEvent,
    TaskDoneEvent,
    TaskPlanPostedEvent,
    TaskProgressEvent,
    TaskStartedEvent,
)
from ydk.models.gate import GateStatus
from ydk.models.pm import TaskCreate

if TYPE_CHECKING:
    from ydk.core.git_worktree import WorktreeManager
    from ydk.core.verifier import Verifier
    from ydk.models.verification import CheckResult
    from ydk.repositories.protocols import LifecycleTaskRepository

logger = logging.getLogger("ydk.task_lifecycle")


class TaskLifecycle:
    """Orchestrate the full task lifecycle."""

    def __init__(
        self,
        repo: LifecycleTaskRepository,
        events: EventBus,
        worktree_mgr: WorktreeManager,
        verifier: Verifier,
        project_root: Path = Path("."),
        worktree_isolation: bool = True,
    ) -> None:
        self._repo = repo
        self._events = events
        self._worktree = worktree_mgr
        self._verifier = verifier
        self._root = project_root
        self._worktree_isolation = worktree_isolation

    def start(
        self, task_id: str, session_id: str | None = None, base_branch: str | None = None, force: bool = False
    ) -> dict:
        """Start a task: create worktree (if enabled), update status, emit event.

        When *base_branch* is provided the worktree/branch is created from that
        ref.  Otherwise it defaults to HEAD (the current branch).

        When *force* is True and the task is already in-progress, the old
        worktree is cleaned up and the task is restarted.

        Returns task detail dict.
        """
        start_time = time.monotonic()
        logger.info("Starting task %s", task_id)
        task = self._repo.get_task(task_id)

        # Guard against starting an already-started task
        if task.status == "in-progress":
            if force:
                logger.info("Force-restarting task %s — cleaning up old worktree", task_id)
                self._worktree.cleanup(task_id)
            else:
                raise ValueError(f"Task {task_id} is already in progress")

        # Check dependencies
        deps = self._repo.check_dependencies(task_id)
        unresolved = [d for d in deps if not d.resolved]
        if unresolved:
            ids = [d.task_id for d in unresolved]
            raise ValueError(f"Unresolved dependencies: {ids}")

        # Check gates
        if task.gates:
            unresolved_gates = [g for g in task.gates if g.status != GateStatus.RESOLVED]
            if unresolved_gates:
                gate_ids = [g.id for g in unresolved_gates]
                raise ValueError(f"Unresolved gates: {gate_ids}")

        # Create worktree or just a branch depending on config
        if self._worktree_isolation:
            worktree_path = self._worktree.create(task_id, task.title, base_branch=base_branch)
            summary = f"Worktree created at {worktree_path}"
        else:
            # Create branch only, no worktree
            branch = f"task/{task_id}"
            if task.title:
                slug = re.sub(r"[^a-z0-9-]", "", task.title.lower().replace(" ", "-"))[:30].strip("-")
                branch = f"task/{task_id}-{slug}"
            base = base_branch or "HEAD"
            subprocess.run(
                ["git", "checkout", "-b", branch, base],
                cwd=str(self._root),
                capture_output=True,
            )
            worktree_path = self._root
            summary = f"Branch {branch} created from {base} (worktree isolation disabled)"

        # Store active task context (branch + base) for PR creation
        active_task_context = {
            "task_id": task_id,
            "base_branch": base_branch or "main",
        }
        active_task_file = self._root / ".ydk" / "active-task.json"
        active_task_file.parent.mkdir(parents=True, exist_ok=True)
        active_task_file.write_text(json.dumps(active_task_context))

        # Update status
        self._repo.update_status(task_id, "in-progress")
        self._repo.assign(task_id, "agent")
        self._repo.add_label(task_id, "in-progress")

        # Store session ID if provided
        if session_id:
            self._repo.add_comment(task_id, f"Session: {session_id}")

        # Emit event (async -- doesn't block)
        self._events.emit(TaskStartedEvent(task_id=task_id, summary=summary))

        elapsed = time.monotonic() - start_time
        logger.info("Task %s started in %.1fs — %s", task_id, elapsed, summary)

        return {"task": task, "worktree": str(worktree_path), "session_id": session_id}

    def plan(self, task_id: str, plan_text: str) -> None:
        """Post implementation plan."""
        self._repo.add_comment(task_id, f"## Implementation Plan\n\n{plan_text}")
        self._events.emit(TaskPlanPostedEvent(task_id=task_id, plan=plan_text))

    def progress(self, task_id: str, message: str) -> None:
        """Post progress update."""
        self._repo.add_comment(task_id, message)
        self._events.emit(TaskProgressEvent(task_id=task_id, message=message))

    def block(self, task_id: str, reason: str, detail: str) -> None:
        """Mark task as blocked."""
        self._repo.update_status(task_id, f"blocked-by-{reason}")
        self._repo.add_label(task_id, f"blocked-by-{reason}")
        self._repo.remove_label(task_id, "in-progress")
        self._repo.add_comment(task_id, f"**Blocked ({reason}):** {detail}")
        self._events.emit(TaskBlockedEvent(task_id=task_id, reason=reason, detail=detail))

    def done(self, task_id: str, *, summary: str | None = None, skip_plugins: list[str] | None = None) -> dict:
        """Complete a task: run verifications, capture proofs, create PR.

        When *summary* is provided it is written to ``summary.md`` in the
        proof directory so the PR body builder can include it.

        When *skip_plugins* is provided, each named plugin is re-verified
        independently.  Only plugins that genuinely FAIL can be skipped.
        If a plugin passes, the skip is rejected with an error.

        Returns {"passed": bool, "pr_url": str, "report": VerificationReport}
        """
        from ydk.core.pr_template import PRBodyBuilder
        from ydk.core.proof_capture import ProofCapture

        done_start = time.monotonic()
        logger.info("Completing task %s — running verifications", task_id)

        # Resolve the task's actual worktree so verification scans the tree
        # the task was implemented in, not wherever this process's cwd
        # happens to be (e.g. `ydk task done` invoked from the main
        # checkout instead of from inside the worktree). Falls back to
        # self._root when worktree isolation is off or no worktree exists.
        scan_root = self._worktree.get_worktree_path(task_id) or self._root

        # Collect files associated with this task's TODOs for scoped verification
        from ydk.core.todo_manager import TodoManager

        todo_mgr = TodoManager(scan_root)
        try:
            all_todos = todo_mgr.list_todos()
            task_todos = [t for t in all_todos if t.task_id == task_id]
            task_files = list({t.file for t in task_todos})
        except Exception:
            task_files = []
            logger.debug("No TODO registry — verification will use git diff scoping")

        # Build context scoped to task files
        context: dict[str, object] = {
            "project_root": str(scan_root),
            "task_id": task_id,
        }
        if task_files:
            context["changed_files"] = task_files

        # Run verifications scoped to task files
        report = asyncio.run(self._verifier.run_all(trigger="pre-push", context=context))

        # Handle skip-plugin requests with internal re-verification
        if skip_plugins:
            for plugin_name in skip_plugins:
                plugin_check = next((c for c in report.checks if c.name == plugin_name), None)
                if plugin_check and plugin_check.passed:
                    # Plugin PASSES — cannot skip a working plugin
                    raise ValueError(
                        f"Cannot skip plugin '{plugin_name}' — it passes successfully. "
                        "Only genuinely failing plugins can be skipped."
                    )
                elif plugin_check and not plugin_check.passed:
                    # Plugin genuinely fails — allow skip, log proof
                    logger.warning(
                        "Skipping plugin '%s' — verified failure: %s",
                        plugin_name,
                        plugin_check.output[:200],
                    )
                # else: plugin wasn't in the run (not found) — ignore silently

            # Recalculate pass/fail excluding skipped plugins
            non_skipped = [c for c in report.checks if c.name not in skip_plugins]
            all_passed = all(c.passed for c in non_skipped) if non_skipped else True
        else:
            all_passed = report.all_passed

        if not all_passed:
            from ydk.core.auto_repair import RepairLoop

            loop = RepairLoop()
            structured_errors = loop.format_errors(report)

            failures = [c for c in report.checks if not c.passed and c.name not in (skip_plugins or [])]
            failure_msg = "\n".join(f"FAIL {c.name}: {c.output[:100]}" for c in failures)

            self._repo.add_comment(task_id, f"**Verification FAILED:**\n{failure_msg}")
            return {"passed": False, "report": report, "structured_errors": structured_errors}

        # Check UI screenshot requirement before proof capture
        task = self._repo.get_task(task_id)
        if self._task_has_ui_components(task):
            screenshots_dir = self._root / ".ydk" / "proofs" / task_id / "screenshots"
            if not screenshots_dir.is_dir() or not list(screenshots_dir.iterdir()):
                msg = (
                    "UI task requires screenshot proof. "
                    "Use playwright-cli to capture screenshots to "
                    f".ydk/proofs/{task_id}/screenshots/ before running ydk task done."
                )
                self._repo.add_comment(task_id, f"**Screenshot proof missing:** {msg}")
                return {"passed": False, "error": msg}

        # Capture proof files deterministically from the verification report
        proof_dir = self._root / ".ydk" / "proofs" / task_id
        pc = ProofCapture(proof_dir)

        if summary:
            pc.write_summary(task_id, summary)

        artifacts = pc.save_report(report)

        # The JSON report is already saved by save_report; keep proof_path for event
        proof_path = artifacts.verification_report_path

        # Write verified flag to avoid double-verification in pre-push hook
        self._write_verified_flag()

        # Check TODO resolution for assigned TODOs
        todo_warnings = self._check_todo_resolution(task_id)

        # Check that xfail markers for this task's TODOs have been removed
        xfail_warnings = self._check_xfail_removed(task_id, task_files)
        if xfail_warnings:
            error_msg = f"Task incomplete: {len(xfail_warnings)} tests still marked as xfail for this task's TODOs"
            details = "\n".join(f"  - {w}" for w in xfail_warnings)
            self._repo.add_comment(task_id, f"**xfail check FAILED:**\n{error_msg}\n{details}")
            return {"passed": False, "error": error_msg, "xfail_warnings": xfail_warnings}

        # Build deterministic PR body from proof files
        pr_builder = PRBodyBuilder()
        pr_body = pr_builder.build(task_id, proof_dir)

        # Final gate: validate the PR body itself. This must run *after* the
        # body is built (the plugin needs the real pr_body in context), so it
        # cannot be part of the earlier verification batch — running it there
        # would always fail since no PR body exists yet at that point.
        skip_pr_body_check = bool(skip_plugins) and "pr-body-validation" in skip_plugins
        if not skip_pr_body_check:
            pr_body_check = self._run_pr_body_validation(pr_body, context)
            if pr_body_check is not None and not pr_body_check.passed:
                self._repo.add_comment(task_id, f"**pr-body-validation FAILED:**\n{pr_body_check.output}")
                return {"passed": False, "error": pr_body_check.output, "pr_body_check": pr_body_check}

        # Create PR with deterministic body (task already fetched above for UI check)
        pr_url = self._create_pr(task_id, task=task, report=report, pr_body_override=pr_body)

        # Post proof to issue
        proof_summary = "\n".join(f"OK {c.name} ({c.duration_seconds}s)" for c in report.checks)
        self._repo.add_comment(task_id, f"## Verification Proof\n\n{proof_summary}\n\nPR: {pr_url}")
        self._repo.update_status(task_id, "in-review")
        self._repo.remove_label(task_id, "in-progress")
        self._repo.add_label(task_id, "in-review")

        # Remove active-task.json so SubagentStop hook allows session to end
        active_task_file = self._root / ".ydk" / "active-task.json"
        if active_task_file.exists():
            active_task_file.unlink()

        self._events.emit(TaskDoneEvent(task_id=task_id, pr_url=pr_url, proof_path=str(proof_path)))

        done_elapsed = time.monotonic() - done_start
        logger.info("Task %s done in %.1fs — PR: %s", task_id, done_elapsed, pr_url)

        result: dict = {"passed": True, "pr_url": pr_url, "report": report, "artifacts": artifacts}
        if todo_warnings:
            result["todo_warnings"] = todo_warnings
        return result

    def _run_pr_body_validation(self, pr_body: str, context: dict[str, object]) -> CheckResult | None:
        """Run the ``pr-body-validation`` plugin as a final gate before PR creation.

        Invoked explicitly (by name) rather than through the normal
        trigger-based batch, since it depends on the real PR body which
        only exists once ``pr_builder.build()`` has run. Returns ``None``
        when the plugin isn't installed, in which case the gate is a no-op.
        """
        plugins = self._verifier.discover_plugins()
        matched = self._verifier.filter_by_name(plugins, "pr-body-validation")
        if not matched:
            return None

        plugin_context = dict(context)
        plugin_context["pr_body"] = pr_body
        results = asyncio.run(self._verifier.run_layer(matched, plugin_context))
        return results[0] if results else None

    def _check_todo_resolution(self, task_id: str) -> list[str]:
        """Check if TODOs assigned to this task are resolved.

        Automatically marks verified TODOs as done. Returns warnings for
        any TODO that still has NotImplementedError.
        """
        from ydk.core.todo_manager import TodoError, TodoManager

        warnings: list[str] = []
        todo_mgr = TodoManager(self._root)
        try:
            all_todos = todo_mgr.list_todos()
        except Exception:
            logger.debug("No TODO registry found — skipping TODO check")
            return warnings

        task_todos = [t for t in all_todos if t.task_id == task_id]
        for todo in task_todos:
            try:
                if todo_mgr.verify_done(todo.id):
                    todo_mgr.done(todo.id)
                    logger.info("Auto-resolved TODO %s", todo.id)
                else:
                    msg = f"TODO {todo.id} still has NotImplementedError in {todo.file}"
                    warnings.append(msg)
                    logger.warning(msg)
            except TodoError as exc:
                warnings.append(str(exc))
        return warnings

    def _check_xfail_removed(self, task_id: str, task_files: list[str]) -> list[str]:
        """Check that xfail markers for this task's TODOs are removed.

        Scans test files corresponding to the task's source files for
        @pytest.mark.xfail markers whose reason references TODOs assigned
        to this task.  Returns a list of warning strings for any remaining
        xfail markers.
        """
        warnings: list[str] = []

        # Derive test file paths from source files
        test_files = self._derive_test_files(task_files)

        # Also get TODO IDs assigned to this task
        from ydk.core.todo_manager import TodoManager

        todo_mgr = TodoManager(self._root)
        try:
            all_todos = todo_mgr.list_todos()
            task_todo_ids = {t.id for t in all_todos if t.task_id == task_id}
        except Exception:
            task_todo_ids = set()

        if not task_todo_ids:
            return warnings

        for test_file in test_files:
            full_path = self._root / test_file
            if not full_path.exists():
                continue
            content = full_path.read_text(encoding="utf-8")
            # Find xfail markers that reference YDK TODOs
            xfails = re.findall(r'@pytest\.mark\.xfail\(reason="(YDK-TODO-\d+[^"]*?)"\)', content)
            for xfail_reason in xfails:
                todo_match = re.search(r"YDK-TODO-(\d+)", xfail_reason)
                if todo_match:
                    todo_id = f"YDK-TODO-{todo_match.group(1)}"
                    if todo_id in task_todo_ids:
                        warnings.append(f"Test still xfail: {xfail_reason} in {test_file}")

        return warnings

    def _derive_test_files(self, source_files: list[str]) -> list[str]:
        """Derive test file paths from source file paths.

        Maps source files to their likely test counterparts:
        - app/core/services/foo.py -> tests/unit/test_foo.py
        - app/api/routes/foo.py -> tests/integration/api/test_foo_routes.py
        - Any path with 'services' -> tests/unit/test_{name}.py
        """
        test_files: list[str] = []
        seen: set[str] = set()

        for src in source_files:
            parts = Path(src).parts
            stem = Path(src).stem

            # Route files -> integration tests
            if "routes" in parts or "api" in parts:
                candidate = f"tests/integration/api/test_{stem}_routes.py"
                if candidate not in seen:
                    test_files.append(candidate)
                    seen.add(candidate)

            # Service files -> unit tests
            if "services" in parts or "core" in parts:
                candidate = f"tests/unit/test_{stem}.py"
                if candidate not in seen:
                    test_files.append(candidate)
                    seen.add(candidate)

            # Generic: tests/test_{stem}.py
            candidate = f"tests/test_{stem}.py"
            if candidate not in seen:
                test_files.append(candidate)
                seen.add(candidate)

        return test_files

    @staticmethod
    def _task_has_ui_components(task: object) -> bool:
        """Check if the task references UI-related components (routes, pages)."""
        from ydk.models.pm import TaskDetail

        if not isinstance(task, TaskDetail):
            return False
        ui_prefixes = ("ydk:page:", "ydk:route:")
        return any(ref.startswith(ui_prefixes) for ref in task.component_refs)

    def discover(self, task_id: str, new_title: str, new_body: str) -> str:
        """Create a new task discovered during implementation."""
        task = self._repo.get_task(task_id)
        new_task = TaskCreate(
            title=new_title,
            story_id=task.story_id,
            spec_refs=[],
            dependencies=[task_id],
            description=f"Discovered from #{task_id}.\n\n{new_body}",
            acceptance_criteria=[],
            test_strategy="TBD",
        )
        result = self._repo.create_task(new_task)
        new_id = result.id or str(result.number)
        self._repo.add_comment(task_id, f"Discovered new task: {new_title} (#{new_id})")
        return new_id

    def _write_verified_flag(self) -> None:
        """Write a .ydk/.verified flag file with a timestamp.

        The pre-push hook checks this flag: if recent (< 5 minutes), it
        skips verification to avoid double-running after ``ydk task done``.
        """
        flag_path = self._root / ".ydk" / ".verified"
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.write_text(str(time.time()))

    def _build_pr_body(
        self,
        task_id: str,
        task: object | None = None,
        report: object | None = None,
    ) -> str:
        """Build a full PR body with verification proof and command outputs.

        The generated body always includes ``## Summary`` and ``## Test Plan``
        sections so that downstream PR-body checks (CI and the
        ``pr-body-validation`` verification plugin) pass without manual editing.
        """
        from ydk.models.pm import TaskDetail
        from ydk.models.verification import VerificationReport

        lines: list[str] = []

        # --- Summary section (always present) ---
        lines.append("## Summary")
        lines.append("")
        if isinstance(task, TaskDetail):
            lines.append(f"Task **{task_id}**: {task.title}")
            if task.story_id:
                lines.append(f"**Story**: {task.story_id}")
            if task.spec_refs:
                lines.append(f"**Spec refs**: {', '.join(task.spec_refs)}")
        else:
            lines.append(f"Task {task_id}")
        lines.append("")

        # Collect changed files from git
        worktree = self._worktree.get_worktree_path(task_id)
        cwd = str(worktree) if worktree else str(self._root)
        diff_result = subprocess.run(
            ["git", "diff", "--name-only", "main"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        changed_files = [f.strip() for f in diff_result.stdout.strip().splitlines() if f.strip()]
        if changed_files:
            lines.append("## Files Changed")
            lines.append("")
            lines.extend(f"- `{f}`" for f in changed_files)
            lines.append("")

        # Verification proof with actual command outputs
        if isinstance(report, VerificationReport) and report.checks:
            lines.append("## Verification Proof")
            lines.append("")
            for check in report.checks:
                status = "PASSED" if check.passed else "FAILED"
                lines.append(f"### {check.name} ({status})")
                lines.append("```console")
                lines.append(check.output)
                lines.append("```")
                lines.append("")

        # Screenshots
        screenshot_lines = self._collect_screenshots(task_id)
        if screenshot_lines:
            lines.append("## Screenshots")
            lines.append("")
            lines.extend(screenshot_lines)
            lines.append("")

        # --- Test Plan section (always present) ---
        lines.append("## Test Plan")
        lines.append("")
        if isinstance(report, VerificationReport) and report.checks:
            lines.append("Automated verification proof included above.")
            passed_count = sum(1 for c in report.checks if c.passed)
            total_count = len(report.checks)
            lines.append(f"- {passed_count}/{total_count} checks passed")
        else:
            lines.append("- [ ] Verification pending")
        lines.append("")

        # Proof completeness warning
        if not isinstance(report, VerificationReport) or not report.checks:
            lines.append("> **Warning**: PR body proof is incomplete — no verification output attached.")
            lines.append("")

        # Closing reference
        lines.append(f"Closes #{task_id}")
        return "\n".join(lines)

    def _collect_screenshots(self, task_id: str) -> list[str]:
        """Check for screenshots in .ydk/proofs/<task_id>/screenshots/."""
        screenshots_dir = self._root / ".ydk" / "proofs" / task_id / "screenshots"
        if not screenshots_dir.is_dir():
            return []
        lines: list[str] = []
        for img in sorted(screenshots_dir.iterdir()):
            if img.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                rel_path = f".ydk/proofs/{task_id}/screenshots/{img.name}"
                label = img.stem.replace("-", " ").replace("_", " ")
                lines.append(f"![{label}](/{rel_path})")
        return lines

    def _create_pr(
        self,
        task_id: str,
        task: object | None = None,
        report: object | None = None,
        pr_body_override: str | None = None,
    ) -> str:
        """Create PR for the task. Returns PR URL.

        When *pr_body_override* is provided it is used as-is instead of
        building the body from the verification report.  This is the path
        used by the deterministic proof capture system.

        For GitHub remotes, attempts ``gh pr create``.
        Falls back to a local reference if ``gh`` is not available or fails.
        """
        import shutil
        import tempfile

        worktree = self._worktree.get_worktree_path(task_id)
        cwd = str(worktree) if worktree else str(self._root)

        # Push the branch
        subprocess.run(
            ["git", "push", "-u", "origin", "HEAD"],
            cwd=cwd,
            capture_output=True,
        )

        # Use override body if provided, else build from report
        pr_body = pr_body_override or self._build_pr_body(task_id, task=task, report=report)

        # Try gh pr create if available
        if shutil.which("gh"):
            # Get actual current branch name (not constructed)
            branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=cwd,
                capture_output=True,
                text=True,
            )
            actual_branch = branch_result.stdout.strip()

            # Read base branch from active task context
            active_task_file = self._root / ".ydk" / "active-task.json"
            base_branch = "main"
            if active_task_file.exists():
                try:
                    task_ctx = json.loads(active_task_file.read_text())
                    base_branch = task_ctx.get("base_branch", "main")
                except (json.JSONDecodeError, OSError):
                    pass

            # Pass the body via --body-file rather than inline: proof-rich
            # bodies can be tens of KB, which overflows the Windows
            # CreateProcess command-line length limit (WinError 206) when
            # passed as a literal argument.
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as body_file:
                body_file.write(pr_body)
                body_file_path = body_file.name

            try:
                result = subprocess.run(
                    [
                        "gh",
                        "pr",
                        "create",
                        "--title",
                        f"Task {task_id}: {getattr(task, 'title', task_id)}",
                        "--body-file",
                        body_file_path,
                        "--head",
                        actual_branch,
                        "--base",
                        base_branch,
                    ],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                )
            finally:
                Path(body_file_path).unlink(missing_ok=True)

            if result.returncode == 0:
                url = result.stdout.strip()
                if url:
                    return url
            else:
                logger.warning("gh pr create failed: %s", result.stderr.strip()[:200])

        # Fallback: return a local reference
        return f"local://{task_id}/pr-pending"

"""Quick dev fast path — streamlined setup for small changes."""

from __future__ import annotations

import hashlib
import subprocess
from typing import TYPE_CHECKING

from ydk.core.active_task import QUICK_BRANCH_TYPES, ActiveTasks, update_active_tasks
from ydk.core.config import load_config
from ydk.core.git_worktree import WorktreeManager
from ydk.models.pm import TaskCreate
from ydk.models.quickdev import QuickDevContext
from ydk.repositories.factory import get_task_repository
from ydk.repositories.local.frontmatter import render_frontmatter
from ydk.services.git import default_branch, resolve_start_sha

if TYPE_CHECKING:
    from pathlib import Path


def _generate_task_id(description: str) -> str:
    """Generate a short task ID from the description."""
    h = hashlib.sha256(description.encode()).hexdigest()[:6]
    return f"QD-{h}"


def _branch_type(description: str) -> str:
    """Derive a CI-allowed branch type prefix from a conventional-commit-style description."""
    if ":" in description:
        candidate = description.split(":", 1)[0].strip().lower()
        if candidate in QUICK_BRANCH_TYPES:
            return candidate
    return "chore"


def _slugify(text: str, max_len: int = 40) -> str:
    """Convert text to a branch-safe slug."""
    slug = text.lower()
    slug = "".join(c if (c.isascii() and c.isalnum()) or c == "-" else "-" for c in slug)
    # Collapse multiple hyphens
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:max_len]


def _write_active_task(project_root: Path, task_id: str, base_branch: str) -> dict[str, str] | None:
    """Record *task_id* in active-task.json so PR creation can find it.

    Merges into the existing per-task map rather than clobbering it, matching
    the format used by ``TaskLifecycle.start``. Returns any entry it replaced.
    """
    prior: list[dict[str, str] | None] = []

    def mutate(tasks: ActiveTasks) -> ActiveTasks:
        prior.append(tasks.get(task_id))
        return {**tasks, task_id: {"base_branch": base_branch}}

    update_active_tasks(project_root, mutate)
    return prior[0] if prior else None


def _rollback(
    project_root: Path,
    task_id: str,
    prior_entry: dict[str, str] | None,
    task_file: Path | None,
    prior_bytes: bytes | None,
) -> None:
    """Undo task state written before a failed worktree creation."""

    def restore(tasks: ActiveTasks) -> ActiveTasks:
        rest = {k: v for k, v in tasks.items() if k != task_id}
        return {**rest, task_id: prior_entry} if prior_entry is not None else rest

    update_active_tasks(project_root, restore)
    if task_file is None:
        return
    if prior_bytes is None:
        task_file.unlink(missing_ok=True)
    else:
        task_file.write_bytes(prior_bytes)


def _find_relevant_components(project_root: Path, description: str) -> list[str]:
    """Find components that might be relevant to the description."""
    components_dir = project_root / ".ydk" / "components"
    if not components_dir.is_dir():
        return []

    relevant: list[str] = []
    desc_lower = description.lower()
    for f in sorted(components_dir.rglob("*.yaml")):
        name = f.stem.lower()
        # Simple keyword match
        if name in desc_lower or any(word in name for word in desc_lower.split() if len(word) > 3):
            relevant.append(f.stem)

    return relevant


class QuickDevSetup:
    """Set up a lightweight workspace for small changes.

    Does NOT implement the change — just creates the task, branch, and context.
    """

    def setup(self, description: str, project_root: Path, base_branch: str | None = None) -> QuickDevContext:
        """Create a lightweight task, branch, and output context.

        Returns a QuickDevContext with everything a coding agent needs.
        """
        branch_type = _branch_type(description)
        # Fail fast (before any task is created) if the base cannot be resolved.
        start_sha = resolve_start_sha(project_root, base_branch)
        config = load_config(project_root / ".ydk" / "config.yaml")
        remote = config.project.remote or "local"
        task_file: Path | None = None
        prior_task_bytes: bytes | None = None

        if remote == "local":
            task_id = _generate_task_id(description)

            # Write a minimal task file
            tasks_dir = project_root / ".ydk" / "tasks"
            tasks_dir.mkdir(parents=True, exist_ok=True)

            task_file = tasks_dir / f"{task_id}.md"
            prior_task_bytes = task_file.read_bytes() if task_file.exists() else None
            task_file.write_text(
                render_frontmatter(
                    {
                        "id": task_id,
                        "title": description,
                        "status": "in-progress",
                        "type": "quickdev",
                    },
                    description,
                ),
                encoding="utf-8",
            )
        else:
            # Non-local remote: create the task on the remote issue tracker
            # so it's visible to `list`/`ready`, and use its issue number as
            # the task ID. No local QD file is written.
            #
            # get_task_repository() reads config relative to the current
            # working directory (like every other CLI command), so callers
            # must invoke setup() with cwd == project_root for the remote it
            # resolves here to match the one read above.
            repo = get_task_repository()
            detail = repo.create_task(TaskCreate(title=description, labels=["in-progress"]))
            task_id = str(detail.number)

        prior_entry = _write_active_task(project_root, task_id, base_branch or default_branch(project_root))

        branch = f"{branch_type}/{task_id.lower()}-{_slugify(description)}"

        # Isolated worktree forked from the base; never touches the main checkout.
        try:
            worktree_path = WorktreeManager(project_root).create(
                task_id, base_branch=base_branch, branch_name=branch, start_point=start_sha
            )
        except RuntimeError:
            _rollback(project_root, task_id, prior_entry, task_file, prior_task_bytes)
            raise
        except subprocess.CalledProcessError as exc:
            _rollback(project_root, task_id, prior_entry, task_file, prior_task_bytes)
            detail = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
            msg = f"Failed to create worktree/branch {branch}: {detail}"
            raise RuntimeError(msg) from exc

        # Find relevant components
        components = _find_relevant_components(project_root, description)

        # Build testing guidance
        testing_guidance = "Run the project test suite after changes. Focus on unit tests for the modified area."

        return QuickDevContext(
            task_id=task_id,
            branch=branch,
            description=description,
            worktree=str(worktree_path),
            components=components,
            testing_guidance=testing_guidance,
        )

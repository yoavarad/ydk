"""Git worktree management for task isolation."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


class WorktreeManager:
    """Create and manage git worktrees for task branches."""

    def __init__(self, project_root: Path = Path(".")) -> None:
        self._root = project_root

    def create(self, task_id: str, description: str = "", base_branch: str | None = None) -> Path:
        """Create a worktree + branch for a task.

        Branch: task/{task_id}-{description}
        Worktree: .ydk/worktrees/{task_id}/
        Returns the worktree path.

        When *base_branch* is provided the new branch is created from that ref.
        Otherwise it defaults to HEAD (the current branch).

        Raises RuntimeError if called from inside an existing worktree.
        """
        # Refuse to create worktree from inside another worktree
        git_indicator = self._root / ".git"
        if git_indicator.is_file():
            msg = (
                "Cannot create worktree: you are already inside a git worktree. "
                "Run 'ydk task start' from the main repository checkout instead."
            )
            raise RuntimeError(msg)
        branch = f"task/{task_id}"
        if description:
            slug = re.sub(r"[^a-z0-9-]", "", description.lower().replace(" ", "-"))[:30].strip("-")
            branch = f"task/{task_id}-{slug}"

        worktree_path = self._root / ".ydk" / "worktrees" / task_id
        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        base = base_branch or "HEAD"

        # Create branch from the specified base (defaults to HEAD)
        subprocess.run(
            ["git", "branch", branch, base],
            cwd=str(self._root),
            capture_output=True,
        )
        # Create worktree
        subprocess.run(
            ["git", "worktree", "add", str(worktree_path), branch],
            cwd=str(self._root),
            capture_output=True,
            check=True,
        )
        return worktree_path

    def cleanup(self, task_id: str) -> None:
        """Remove worktree and delete branch."""
        worktree_path = self._root / ".ydk" / "worktrees" / task_id
        if worktree_path.exists():
            subprocess.run(
                ["git", "worktree", "remove", str(worktree_path), "--force"],
                cwd=str(self._root),
                capture_output=True,
            )
        # Find and delete the branch
        result = subprocess.run(
            ["git", "branch", "--list", f"task/{task_id}*"],
            cwd=str(self._root),
            capture_output=True,
            text=True,
        )
        for branch in result.stdout.strip().splitlines():
            branch = branch.strip().lstrip("* ")
            if branch:
                subprocess.run(
                    ["git", "branch", "-D", branch],
                    cwd=str(self._root),
                    capture_output=True,
                )

    def get_worktree_path(self, task_id: str) -> Path | None:
        """Get worktree path if it exists."""
        path = self._root / ".ydk" / "worktrees" / task_id
        return path if path.exists() else None

    def list_worktrees(self) -> list[str]:
        """List active worktree task IDs."""
        wt_dir = self._root / ".ydk" / "worktrees"
        if not wt_dir.exists():
            return []
        return [d.name for d in wt_dir.iterdir() if d.is_dir()]

"""Quick dev fast path — streamlined setup for small changes."""

from __future__ import annotations

import hashlib
import subprocess
from typing import TYPE_CHECKING

from ydk.models.quickdev import QuickDevContext

if TYPE_CHECKING:
    from pathlib import Path


def _generate_task_id(description: str) -> str:
    """Generate a short task ID from the description."""
    h = hashlib.sha256(description.encode()).hexdigest()[:6]
    return f"QD-{h}"


_CONVENTIONAL_TYPES = frozenset({"feat", "fix", "docs", "chore", "refactor", "test", "ci", "perf", "release", "task"})


def _branch_type(description: str) -> str:
    """Derive a CI-allowed branch type prefix from a conventional-commit-style description."""
    if ":" in description:
        candidate = description.split(":", 1)[0].strip().lower()
        if candidate in _CONVENTIONAL_TYPES:
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

    def setup(self, description: str, project_root: Path) -> QuickDevContext:
        """Create a lightweight task, branch, and output context.

        Returns a QuickDevContext with everything a coding agent needs.
        """
        task_id = _generate_task_id(description)
        branch_type = _branch_type(description)
        branch = f"{branch_type}/{task_id.lower()}-{_slugify(description)}"

        # Write a minimal task file
        tasks_dir = project_root / ".ydk" / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)

        task_file = tasks_dir / f"{task_id}.md"
        task_file.write_text(
            f"---\nid: {task_id}\ntitle: {description}\nstatus: in-progress\ntype: quickdev\n---\n\n{description}\n",
            encoding="utf-8",
        )

        # Create branch (best-effort — may fail if not in a git repo)
        subprocess.run(
            ["git", "checkout", "-b", branch],
            cwd=str(project_root),
            capture_output=True,
        )

        # Find relevant components
        components = _find_relevant_components(project_root, description)

        # Build testing guidance
        testing_guidance = "Run the project test suite after changes. Focus on unit tests for the modified area."

        return QuickDevContext(
            task_id=task_id,
            branch=branch,
            description=description,
            components=components,
            testing_guidance=testing_guidance,
        )

"""Concrete git implementation using subprocess."""

from __future__ import annotations

import subprocess
from pathlib import Path


class LocalGitService:
    """Git operations via subprocess."""

    def __init__(self, cwd: str | None = None) -> None:
        self._cwd = cwd

    def changed_files(self, directory: str, base_ref: str = "main", extension: str = ".md") -> list[str]:
        """Return files changed vs base_ref, filtered by extension.

        Falls back to git ls-files if diff fails (e.g. base ref doesn't exist).
        """
        result = subprocess.run(
            ["git", "diff", base_ref, "--name-only", "--", directory],
            capture_output=True,
            text=True,
            cwd=self._cwd,
        )
        if result.returncode != 0:
            # Fallback: list tracked files in directory
            result = subprocess.run(
                ["git", "ls-files", "--", directory],
                capture_output=True,
                text=True,
                cwd=self._cwd,
            )

        lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
        return [f for f in lines if f.endswith(extension)]

    def all_files(self, directory: str, extension: str = ".md") -> list[str]:
        """Find all files with the given extension under directory."""
        dir_path = Path(directory)
        if not dir_path.is_dir():
            return []
        return sorted(str(p) for p in dir_path.glob(f"**/*{extension}"))

    def read_content(self, files: list[str]) -> str:
        """Concatenate files into a single string, each prefixed with path."""
        if not files:
            return ""
        sections: list[str] = []
        for filepath in files:
            path = Path(filepath)
            if not path.is_file():
                continue
            content = path.read_text()
            sections.append(f"# File: {filepath}\n\n{content}")
        return "\n\n---\n\n".join(sections)

    def current_branch(self) -> str:
        """Return the current git branch name."""
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=self._cwd,
        )
        if result.returncode != 0:
            msg = f"Failed to get current branch: {result.stderr.strip()}"
            raise RuntimeError(msg)
        return result.stdout.strip()

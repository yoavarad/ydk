"""TODO management — register, track, and verify ignition TODOs.

Manages the lifecycle of NotImplementedError placeholders generated
during ignition scaffolding. Each placeholder gets a unique ID
(YDK-TODO-NNN) and is tracked through open -> in-progress -> done.
"""

from __future__ import annotations

import ast
import logging
import re
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path

from ydk.models.todo import TodoItem, TodoRegistry, TodoStatus

logger = logging.getLogger("ydk.todo_manager")

_TODO_COMMENT_RE = re.compile(r"#\s*YDK-TODO-(\d+):\s*(.*)")


class TodoError(Exception):
    """Raised when a TODO operation fails."""


class TodoManager:
    """Core manager for YDK TODO tracking."""

    def __init__(self, project_root: Path) -> None:
        self._root = project_root
        self._registry_path = project_root / ".ydk" / "todos.yaml"

    def register(
        self,
        file: str,
        line: int,
        method: str,
        component_refs: list[str] | None = None,
        description: str = "",
    ) -> str:
        """Register a new TODO from ignition. Returns the TODO ID."""
        registry = self._load()
        todo_id = f"YDK-TODO-{registry.next_id:03d}"
        registry.todos[todo_id] = TodoItem(
            id=todo_id,
            file=file,
            line=line,
            method=method,
            component_refs=component_refs or [],
            description=description,
        )
        registry.next_id += 1
        self._save(registry)
        logger.info("Registered %s: %s in %s:%d", todo_id, method, file, line)
        return todo_id

    def list_todos(self, status: str | None = None) -> list[TodoItem]:
        """List all TODOs, optionally filtered by status."""
        registry = self._load()
        items = list(registry.todos.values())
        if status is not None:
            items = [t for t in items if t.status.value == status]
        return items

    def get(self, todo_id: str) -> TodoItem:
        """Get a specific TODO by ID."""
        registry = self._load()
        if todo_id not in registry.todos:
            msg = f"TODO not found: {todo_id}"
            raise TodoError(msg)
        return registry.todos[todo_id]

    def assign(self, todo_id: str, task_id: str) -> None:
        """Link a TODO to a Stage 2 task."""
        registry = self._load()
        if todo_id not in registry.todos:
            msg = f"TODO not found: {todo_id}"
            raise TodoError(msg)
        registry.todos[todo_id].task_id = task_id
        self._save(registry)
        logger.info("Assigned %s to task %s", todo_id, task_id)

    def start(self, todo_id: str) -> None:
        """Mark TODO as in-progress."""
        registry = self._load()
        if todo_id not in registry.todos:
            msg = f"TODO not found: {todo_id}"
            raise TodoError(msg)
        registry.todos[todo_id].status = TodoStatus.IN_PROGRESS
        self._save(registry)

    def done(self, todo_id: str) -> None:
        """Mark TODO as done. Verifies the NotImplementedError is gone from the file."""
        registry = self._load()
        if todo_id not in registry.todos:
            msg = f"TODO not found: {todo_id}"
            raise TodoError(msg)
        todo = registry.todos[todo_id]
        if not self.verify_done(todo_id):
            msg = f"Cannot mark {todo_id} as done: NotImplementedError still present in {todo.file}"
            raise TodoError(msg)
        registry.todos[todo_id].status = TodoStatus.DONE
        self._save(registry)
        logger.info("Marked %s as done", todo_id)

    def coverage(self) -> dict:
        """Return coverage stats: total, open, in_progress, done, percentage."""
        registry = self._load()
        todos = list(registry.todos.values())
        total = len(todos)
        open_count = sum(1 for t in todos if t.status == TodoStatus.OPEN)
        in_progress = sum(1 for t in todos if t.status == TodoStatus.IN_PROGRESS)
        done_count = sum(1 for t in todos if t.status == TodoStatus.DONE)
        percentage = (done_count / total * 100) if total > 0 else 0.0
        return {
            "total": total,
            "open": open_count,
            "in_progress": in_progress,
            "done": done_count,
            "percentage": round(percentage, 1),
        }

    def verify_done(self, todo_id: str) -> bool:
        """Check if the file still contains NotImplementedError at the TODO's location.

        Returns True if the TODO is actually resolved (no more NotImplementedError).
        """
        registry = self._load()
        if todo_id not in registry.todos:
            msg = f"TODO not found: {todo_id}"
            raise TodoError(msg)
        todo = registry.todos[todo_id]
        file_path = self._root / todo.file
        if not file_path.exists():
            # File removed entirely — consider the TODO resolved
            return True
        content = file_path.read_text()
        lines = content.splitlines()
        # Check a window around the original line (methods may shift)
        start = max(0, todo.line - 5)
        end = min(len(lines), todo.line + 5)
        window = "\n".join(lines[start:end])
        # Check for the specific TODO marker or generic NotImplementedError near the line
        if f"YDK-TODO-{int(todo_id.split('-')[-1]):03d}" in window and "raise NotImplementedError" in window:
            return False
        # Also check if there's a bare NotImplementedError at the exact line (0-indexed)
        line_idx = todo.line - 1
        return not (0 <= line_idx < len(lines) and "raise NotImplementedError" in lines[line_idx])

    def scan_file(self, file_path: str) -> list[dict]:
        """Scan a Python file for raise NotImplementedError lines.

        Used by ignition to discover TODOs in generated files.
        Returns list of {line, method_name, comment}.
        """
        full_path = self._root / file_path
        if not full_path.exists():
            return []

        content = full_path.read_text()
        results: list[dict] = []

        # Parse the AST to find method context
        try:
            tree = ast.parse(content)
        except SyntaxError:
            logger.warning("Could not parse %s — skipping AST analysis", file_path)
            return self._scan_file_regex(content)

        lines = content.splitlines()
        method_ranges = self._extract_method_ranges(tree)

        for i, line_text in enumerate(lines, start=1):
            stripped = line_text.strip()
            if not stripped.startswith("raise NotImplementedError"):
                continue

            method_name = self._find_enclosing_method(i, method_ranges)
            comment = ""
            comment_match = _TODO_COMMENT_RE.search(line_text)
            if comment_match:
                comment = comment_match.group(2).strip()

            # If no inline comment, look for IMPLEMENT comment on preceding lines
            if not comment:
                comment = self._extract_implement_comment(lines, i)

            results.append(
                {
                    "line": i,
                    "method_name": method_name,
                    "comment": comment,
                }
            )

        return results

    def _scan_file_regex(self, content: str) -> list[dict]:
        """Fallback scanner when AST parsing fails."""
        results: list[dict] = []
        for i, line_text in enumerate(content.splitlines(), start=1):
            stripped = line_text.strip()
            if not stripped.startswith("raise NotImplementedError"):
                continue
            comment = ""
            comment_match = _TODO_COMMENT_RE.search(line_text)
            if comment_match:
                comment = comment_match.group(2).strip()
            results.append(
                {
                    "line": i,
                    "method_name": "<unknown>",
                    "comment": comment,
                }
            )
        return results

    def _extract_method_ranges(self, tree: ast.Module) -> list[tuple[str, int, int]]:
        """Extract (qualified_name, start_line, end_line) for all methods/functions."""
        ranges: list[tuple[str, int, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        name = f"{node.name}.{item.name}"
                        ranges.append((name, item.lineno, item.end_lineno or item.lineno))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not any(
                node.lineno >= s and node.lineno <= e for _, s, e in ranges
            ):
                # Only top-level functions (not nested in classes — those handled above)
                ranges.append((node.name, node.lineno, node.end_lineno or node.lineno))
        return ranges

    def _find_enclosing_method(self, line: int, ranges: list[tuple[str, int, int]]) -> str:
        """Find the method/function enclosing the given line number."""
        for name, start, end in ranges:
            if start <= line <= end:
                return name
        return "<module>"

    @staticmethod
    def _extract_implement_comment(lines: list[str], raise_line: int) -> str:
        """Extract IMPLEMENT comment from lines preceding a raise NotImplementedError.

        Looks backwards from the raise line for '# IMPLEMENT:' comments.
        """
        for offset in range(1, 10):
            idx = raise_line - 1 - offset  # lines is 0-indexed, raise_line is 1-indexed
            if idx < 0:
                break
            line = lines[idx].strip()
            if line.startswith("# IMPLEMENT:"):
                return line[len("# IMPLEMENT:") :].strip()
            if line.startswith("# YDK-TODO:"):
                # Found the TODO marker but no IMPLEMENT — stop looking
                break
            if not line.startswith("#"):
                # Hit non-comment code — stop looking
                break
        return ""

    def _load(self) -> TodoRegistry:
        """Load the registry from YAML."""
        if not self._registry_path.exists():
            return TodoRegistry()
        raw = yaml.safe_load(self._registry_path.read_text())
        if raw is None:
            return TodoRegistry()
        return TodoRegistry.model_validate(raw)

    def _save(self, registry: TodoRegistry) -> None:
        """Save the registry to YAML."""
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        data = registry.model_dump(mode="json")
        self._registry_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

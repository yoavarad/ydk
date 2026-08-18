"""Delta spec parser — extracts ADDED/MODIFIED/REMOVED operations from markdown files."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ydk.models.change import DeltaOperation, DeltaType

if TYPE_CHECKING:
    from pathlib import Path

_SECTION_PATTERN = re.compile(r"^##\s+(ADDED|MODIFIED|REMOVED)\s*$", re.IGNORECASE)
_BLOCK_PATTERN = re.compile(r"^###\s+(.+)$")
_TARGET_FILE_PATTERN = re.compile(r"^>\s*Target:\s*(.+)$", re.MULTILINE)


def parse_delta_file(content: str, default_target: str = "") -> list[DeltaOperation]:
    """Parse a delta spec markdown file into a list of DeltaOperations.

    Expected format:
        > Target: specs/api.md

        ## ADDED
        ### New Endpoint: POST /users
        content here...

        ## MODIFIED
        ### Endpoint: GET /users
        updated content...

        ## REMOVED
        ### Endpoint: DELETE /legacy
    """
    if not content.strip():
        return []

    target_match = _TARGET_FILE_PATTERN.search(content)
    target_file = target_match.group(1).strip() if target_match else default_target

    lines = content.split("\n")
    operations: list[DeltaOperation] = []
    current_type: DeltaType | None = None
    current_heading: str | None = None
    current_content_lines: list[str] = []

    def _flush() -> None:
        if current_type is not None and current_heading is not None:
            body = "\n".join(current_content_lines).strip()
            operations.append(
                DeltaOperation(
                    delta_type=current_type,
                    target_file=target_file,
                    section_heading=current_heading,
                    content=body,
                )
            )

    for line in lines:
        section_match = _SECTION_PATTERN.match(line)
        if section_match:
            _flush()
            current_type = DeltaType(section_match.group(1).lower())
            current_heading = None
            current_content_lines = []
            continue

        block_match = _BLOCK_PATTERN.match(line)
        if block_match and current_type is not None:
            _flush()
            current_heading = block_match.group(1).strip()
            current_content_lines = []
            continue

        if current_heading is not None:
            current_content_lines.append(line)

    _flush()
    return operations


def parse_delta_directory(delta_dir: Path) -> list[DeltaOperation]:
    """Parse all markdown files in a delta-specs directory."""
    if not delta_dir.is_dir():
        return []

    operations: list[DeltaOperation] = []
    for md_file in sorted(delta_dir.glob("*.md")):
        default_target = md_file.stem
        ops = parse_delta_file(md_file.read_text(), default_target=default_target)
        operations.extend(ops)
    return operations


def apply_operations_to_spec(spec_content: str, operations: list[DeltaOperation]) -> str:
    """Apply delta operations to a canonical spec's content.

    Returns the modified spec content.
    """
    result = spec_content

    for op in operations:
        if op.delta_type == DeltaType.ADDED:
            result = _apply_add(result, op)
        elif op.delta_type == DeltaType.MODIFIED:
            result = _apply_modify(result, op)
        elif op.delta_type == DeltaType.REMOVED:
            result = _apply_remove(result, op)

    return result


def _apply_add(content: str, op: DeltaOperation) -> str:
    block = f"\n\n### {op.section_heading}\n\n{op.content}" if op.content else f"\n\n### {op.section_heading}"
    return content.rstrip() + block + "\n"


def _apply_modify(content: str, op: DeltaOperation) -> str:
    pattern = re.compile(
        rf"(### {re.escape(op.section_heading)}\s*\n)(.*?)(?=\n### |\n## |\Z)",
        re.DOTALL,
    )
    match = pattern.search(content)
    if not match:
        return content

    replacement = f"### {op.section_heading}\n\n{op.content}\n"
    return content[: match.start()] + replacement + content[match.end() :]


def _apply_remove(content: str, op: DeltaOperation) -> str:
    pattern = re.compile(
        rf"\n*### {re.escape(op.section_heading)}\s*\n.*?(?=\n### |\n## |\Z)",
        re.DOTALL,
    )
    return pattern.sub("", content)

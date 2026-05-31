"""Bidirectional parser: Pydantic models <-> structured GitHub Issue markdown.

Task issue body format:

    **Story**: S-001
    **Spec refs**: orders.md#entities, orders.md#error-scenarios
    **Dependencies**: T-001, T-003
    **Test strategy**: Unit tests for domain validation

    ### Description
    Implement order validation rules...

    ### Acceptance Criteria
    - [ ] Insufficient balance raises INSUFFICIENT_BALANCE
    - [x] Invalid symbol raises INVALID_SYMBOL

Story issue body format:

    **Epic**: E-001

    ### Description
    As a trader I want ...

    ### Acceptance Criteria
    - [ ] Can place an order

Epic issue body format:

    ### Description
    The orders epic covers ...
"""

from __future__ import annotations

import re

from odk.models.pm import (
    AcceptanceCriterion,
    Dependency,
    EpicCreate,
    EpicDetail,
    StoryCreate,
    StoryDetail,
    TaskCreate,
    TaskDetail,
    TaskStatus,
)

# ---------------------------------------------------------------------------
# Render: model -> markdown
# ---------------------------------------------------------------------------


def _github_ref(raw_id: str) -> str:
    """Convert an ID to GitHub ``#N`` format when it looks like a number.

    * ``"42"`` -> ``"#42"``
    * ``"S-001"`` / ``"E-001"`` -> ``"#1"`` (strip leading zeros)
    * Already prefixed ``"#42"`` -> ``"#42"`` (no-op)
    """
    if raw_id.startswith("#"):
        return raw_id
    # Try bare numeric first
    try:
        return f"#{int(raw_id)}"
    except ValueError:
        pass
    # Try S-NNN / E-NNN / T-NNN prefix
    if len(raw_id) >= 3 and raw_id[1] == "-":
        try:
            return f"#{int(raw_id[2:])}"
        except ValueError:
            pass
    # Fallback: return as-is (should not happen for GitHub)
    return raw_id


def render_task_body(task: TaskCreate) -> str:
    """Render a TaskCreate into the structured markdown body for a GitHub Issue."""
    lines: list[str] = []
    if task.story_id:
        lines.append(f"**Story**: {_github_ref(task.story_id)}")
    if task.spec_refs:
        lines.append(f"**Spec refs**: {', '.join(task.spec_refs)}")
    if task.component_refs:
        lines.append(f"**Component refs**: {', '.join(task.component_refs)}")
    if task.dependencies:
        dep_ids = [d.task_id if isinstance(d, Dependency) else d for d in task.dependencies]
        lines.append(f"**Dependencies**: {', '.join(dep_ids)}")
    if task.test_strategy:
        lines.append(f"**Test strategy**: {task.test_strategy}")
    if lines:
        lines.append("")
    if task.description:
        lines.append("### Description")
        lines.append(task.description)
        lines.append("")
    if task.acceptance_criteria:
        lines.append("### Acceptance Criteria")
        for ac in task.acceptance_criteria:
            if isinstance(ac, str):
                lines.append(f"- [ ] {ac}")
            else:
                check = "x" if ac.done else " "
                lines.append(f"- [{check}] {ac.text}")
    return "\n".join(lines)


def render_epic_body(epic: EpicCreate) -> str:
    """Render an EpicCreate into markdown body."""
    lines: list[str] = []
    if epic.description:
        lines.append("### Description")
        lines.append(epic.description)
    return "\n".join(lines)


def render_story_body(story: StoryCreate) -> str:
    """Render a StoryCreate into markdown body."""
    lines: list[str] = []
    if story.epic_id:
        lines.append(f"**Epic**: {_github_ref(story.epic_id)}")
        lines.append("")
    if story.description:
        lines.append("### Description")
        lines.append(story.description)
        lines.append("")
    if story.acceptance_criteria:
        lines.append("### Acceptance Criteria")
        for ac in story.acceptance_criteria:
            if isinstance(ac, str):
                lines.append(f"- [ ] {ac}")
            else:
                check = "x" if ac.done else " "
                lines.append(f"- [{check}] {ac.text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Parse: markdown -> model fields
# ---------------------------------------------------------------------------

_FIELD_RE = re.compile(r"^\*\*(.+?)\*\*:\s*(.+)$")
_AC_RE = re.compile(r"^- \[([ x])] (.+)$")


def _parse_body(body: str) -> tuple[dict[str, str], dict[str, str]]:
    """Parse **Key**: value fields and ### sections from a markdown body.

    Returns (fields, sections) where fields maps lowercase key -> value
    and sections maps lowercase heading -> body text.
    """
    fields: dict[str, str] = {}
    sections: dict[str, str] = {}
    current_section: str | None = None
    section_lines: list[str] = []

    for line in body.splitlines():
        # Check for ### heading
        if line.startswith("### "):
            if current_section is not None:
                sections[current_section] = "\n".join(section_lines).strip()
            current_section = line[4:].strip().lower()
            section_lines = []
            continue

        if current_section is not None:
            section_lines.append(line)
            continue

        m = _FIELD_RE.match(line)
        if m:
            key = m.group(1).strip().lower()
            fields[key] = m.group(2).strip()

    if current_section is not None:
        sections[current_section] = "\n".join(section_lines).strip()

    return fields, sections


def _parse_csv(value: str) -> list[str]:
    """Split a comma-separated field value, stripping whitespace."""
    return [v.strip() for v in value.split(",") if v.strip()]


def _parse_acceptance_criteria(text: str) -> list[AcceptanceCriterion]:
    """Extract acceptance criteria from a section body."""
    criteria: list[AcceptanceCriterion] = []
    for line in text.splitlines():
        m = _AC_RE.match(line)
        if m:
            done = m.group(1) == "x"
            criteria.append(AcceptanceCriterion(text=m.group(2).strip(), done=done))
    return criteria


def _gh_state_to_status(state: str, labels: list[str]) -> TaskStatus:
    """Map GitHub issue state + labels to TaskStatus."""
    if state.upper() == "CLOSED":
        return TaskStatus.DONE
    for lbl in labels:
        if lbl == "blocked-by-code":
            return TaskStatus.BLOCKED_BY_CODE
        if lbl == "blocked-by-decision":
            return TaskStatus.BLOCKED_BY_DECISION
        if lbl.startswith("blocked"):
            return TaskStatus.BLOCKED_BY_CODE
    if "in-review" in labels:
        return TaskStatus.IN_REVIEW
    if "in-progress" in labels or "in_progress" in labels:
        return TaskStatus.IN_PROGRESS
    return TaskStatus.OPEN


def parse_task_detail(
    number: int,
    title: str,
    body: str,
    state: str,
    labels: list[str],
    url: str = "",
) -> TaskDetail:
    """Parse a GitHub Issue into a TaskDetail."""
    fields, sections = _parse_body(body or "")
    status = _gh_state_to_status(state, labels)

    ac: list[str | AcceptanceCriterion] = list(_parse_acceptance_criteria(sections.get("acceptance criteria", "")))
    parsed_deps: list[str | Dependency] = list(_parse_csv(fields.get("dependencies", "")))
    return TaskDetail(
        number=number,
        title=title,
        story_id=fields.get("story", "").strip() or None,
        spec_refs=_parse_csv(fields.get("spec refs", "")),
        component_refs=_parse_csv(fields.get("component refs", "")),
        dependencies=parsed_deps,
        description=sections.get("description", ""),
        acceptance_criteria=ac,
        test_strategy=fields.get("test strategy", ""),
        status=status,
        labels=labels,
        url=url,
    )


def parse_story_detail(
    number: int,
    title: str,
    body: str,
    state: str,
    labels: list[str],
    url: str = "",
) -> StoryDetail:
    """Parse a GitHub Issue into a StoryDetail."""
    fields, sections = _parse_body(body or "")
    status = _gh_state_to_status(state, labels)
    return StoryDetail(
        number=number,
        title=title,
        epic_id=fields.get("epic") or None,
        description=sections.get("description", ""),
        acceptance_criteria=_parse_acceptance_criteria(sections.get("acceptance criteria", "")),
        labels=labels,
        status=status,
        url=url,
    )


def parse_epic_detail(
    number: int,
    title: str,
    body: str,
    state: str,
    labels: list[str],
    url: str = "",
) -> EpicDetail:
    """Parse a GitHub Issue into an EpicDetail."""
    _fields, sections = _parse_body(body or "")
    status = _gh_state_to_status(state, labels)
    return EpicDetail(
        number=number,
        title=title,
        description=sections.get("description", ""),
        labels=labels,
        status=status,
        url=url,
    )

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

import json
import logging
import re

from pydantic import ValidationError

from ydk.models.gate import Gate, GateStatus, GateType
from ydk.models.pm import (
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

logger = logging.getLogger(__name__)

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
    if task.gates:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append("### Gates")
        lines.extend(render_gate_line(g) for g in task.gates)
    return "\n".join(lines)


def render_gate_line(gate: Gate) -> str:
    """Render one gate as a ``### Gates`` bullet.

    ``config`` / ``resolved_at`` are carried in a trailing HTML comment (hidden
    in the rendered issue) so the gate round-trips losslessly.
    """
    line = f"- **{gate.id}** ({gate.type}): {gate.description} [{gate.status}]"
    meta: dict[str, object] = {}
    if gate.config:
        meta["config"] = gate.config
    if gate.resolved_at:
        meta["resolved_at"] = gate.resolved_at
    if meta:
        # Escape '>' so a value can never close the HTML comment early.
        encoded = json.dumps(meta, sort_keys=True).replace(">", "\\u003e")
        line += f" <!-- ydk-gate {encoded} -->"
    return line


def set_body_field(body: str, label: str, value: str) -> str:
    """Set a ``**Label**: value`` header field, replacing it or adding it if missing.

    Header fields live before the first ``### `` heading. An empty *value*
    removes the field.
    """
    lines = body.splitlines()
    header_end = next((i for i, line in enumerate(lines) if line.startswith("### ")), len(lines))
    new_line = f"**{label}**: {value}"
    last_field = -1
    for i in range(header_end):
        m = _FIELD_LINE_RE.match(lines[i])
        if not m:
            continue
        if m.group(1).strip().lower() == label.lower():
            if value:
                lines[i] = new_line
            else:
                del lines[i]
            return "\n".join(lines)
        last_field = i
    if not value:
        return body
    if last_field >= 0:
        lines.insert(last_field + 1, new_line)
    elif lines:
        lines[0:0] = [new_line, ""]
    else:
        lines = [new_line]
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
_FIELD_LINE_RE = re.compile(r"^\*\*(.+?)\*\*:(.*)$")
_AC_RE = re.compile(r"^- \[([ x])] (.+)$")
_GATE_RE = re.compile(
    r"^- \*\*(?P<id>.+?)\*\* \((?P<type>[^)]+)\): (?P<desc>.*) \[(?P<status>\w+)\]"
    r"(?: <!-- ydk-gate (?P<meta>\{.*\}) -->)?$"
)


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


def _parse_gates(text: str) -> list[Gate]:
    """Extract gates from a ``### Gates`` section body (see ``render_gate_line``)."""
    gates: list[Gate] = []
    for line in text.splitlines():
        m = _GATE_RE.match(line.strip())
        if not m:
            continue
        try:
            meta = json.loads(m.group("meta")) if m.group("meta") else {}
            gates.append(
                Gate(
                    id=m.group("id"),
                    type=GateType(m.group("type")),
                    description=m.group("desc"),
                    status=GateStatus(m.group("status")),
                    config=meta.get("config", {}),
                    resolved_at=meta.get("resolved_at"),
                )
            )
        except (ValidationError, ValueError, AttributeError):
            logger.warning("Skipping unparseable gate line: %s", line)
            continue
    return gates


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
        session_id=fields.get("session") or None,
        tdd_stage=fields.get("tdd stage") or None,
        gates=_parse_gates(sections.get("gates", "")),
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

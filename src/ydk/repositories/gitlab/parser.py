"""Parse and render structured markdown issue bodies.

The body format is backend-agnostic (same for GitHub and GitLab):

    **Story**: S-001
    **Spec refs**: orders.md#entities, orders.md#error-scenarios
    **Dependencies**: T-001, T-003
    **Test strategy**: Unit tests for domain validation

    ### Description
    ...

    ### Acceptance Criteria
    - [ ] First criterion
    - [x] Second criterion (done)
"""

from __future__ import annotations

import re

from ydk.models.pm import AcceptanceCriterion

# ---------------------------------------------------------------------------
# Render: structured fields -> markdown body
# ---------------------------------------------------------------------------


def render_body(
    *,
    story_id: str | None = None,
    epic_id: str | None = None,
    spec_refs: list[str] | None = None,
    dependencies: list[str] | None = None,
    test_strategy: str = "",
    description: str = "",
    acceptance_criteria: list[str | AcceptanceCriterion] | None = None,
) -> str:
    """Build a markdown issue body from structured fields."""
    lines: list[str] = []

    if story_id:
        lines.append(f"**Story**: {story_id}")
    if epic_id:
        lines.append(f"**Epic**: {epic_id}")
    if spec_refs:
        lines.append(f"**Spec refs**: {', '.join(spec_refs)}")
    if dependencies:
        lines.append(f"**Dependencies**: {', '.join(dependencies)}")
    if test_strategy:
        lines.append(f"**Test strategy**: {test_strategy}")

    if description:
        if lines:
            lines.append("")
        lines.append("### Description")
        lines.append(description)

    if acceptance_criteria:
        if lines:
            lines.append("")
        lines.append("### Acceptance Criteria")
        for ac in acceptance_criteria:
            if isinstance(ac, str):
                lines.append(f"- [ ] {ac}")
            else:
                checkbox = "[x]" if ac.done else "[ ]"
                lines.append(f"- {checkbox} {ac.text}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Parse: markdown body -> structured dict
# ---------------------------------------------------------------------------

_FIELD_PATTERN = re.compile(r"^\*\*(?P<key>[^*]+)\*\*:\s*(?P<value>.+)$")
_AC_PATTERN = re.compile(r"^-\s*\[(?P<check>[xX ])\]\s*(?P<text>.+)$")


def parse_body(body: str) -> dict:
    """Parse a structured markdown body into a dict of fields.

    Returns a dict with keys: story_id, epic_id, spec_refs, dependencies,
    test_strategy, description, acceptance_criteria.
    """
    result: dict = {
        "story_id": None,
        "epic_id": None,
        "spec_refs": [],
        "dependencies": [],
        "test_strategy": "",
        "description": "",
        "acceptance_criteria": [],
    }

    lines = body.split("\n")
    section: str | None = None
    description_lines: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Detect section headers
        if stripped.startswith("### Description"):
            section = "description"
            continue
        if stripped.startswith("### Acceptance Criteria"):
            section = "acceptance_criteria"
            continue

        # Metadata fields (top of body, before any section)
        field_match = _FIELD_PATTERN.match(stripped)
        if field_match and section is None:
            key = field_match.group("key").strip().lower()
            value = field_match.group("value").strip()
            if key == "story":
                result["story_id"] = value
            elif key == "epic":
                result["epic_id"] = value
            elif key == "spec refs":
                result["spec_refs"] = [ref.strip() for ref in value.split(",") if ref.strip()]
            elif key == "dependencies":
                result["dependencies"] = [dep.strip() for dep in value.split(",") if dep.strip()]
            elif key == "test strategy":
                result["test_strategy"] = value
            continue

        # Section content
        if section == "description":
            description_lines.append(line)
        elif section == "acceptance_criteria":
            ac_match = _AC_PATTERN.match(stripped)
            if ac_match:
                done = ac_match.group("check").lower() == "x"
                result["acceptance_criteria"].append(AcceptanceCriterion(text=ac_match.group("text"), done=done))

    # Trim leading/trailing blank lines from description
    desc_text = "\n".join(description_lines).strip()
    result["description"] = desc_text

    return result

"""Test coverage checker — maps components to test files."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import yaml

from odk.models.test_gen import CoverageByType, CoverageReport

if TYPE_CHECKING:
    from pathlib import Path


def _slugify(text: str) -> str:
    """Convert text to lowercase slug fragments for matching."""
    return re.sub(r"[^a-zA-Z0-9]", "_", text).strip("_").lower()


def _build_patterns(component_id: str) -> list[str]:
    """Build filename patterns from a component ID.

    odk:entity:orders/Order -> ["order"]
    odk:route:orders/create -> ["order", "create"]
    """
    parts = component_id.split(":", 2)
    name_part = parts[2] if len(parts) == 3 else component_id
    segments = re.split(r"[/\-_]", name_part)
    return [s.lower() for s in segments if s]


class TestCoverageChecker:
    """Check test coverage for ODK components."""

    def check_coverage(self, components_dir: Path, tests_dir: Path) -> CoverageReport:
        """Scan components and find matching test files.

        For each component, look for test files whose names contain the
        component's namespace/name segments (case-insensitive).
        """
        # Collect all test file stems
        test_stems: list[str] = []
        if tests_dir.is_dir():
            test_stems.extend(tf.stem.lower() for tf in tests_dir.rglob("test_*.py"))

        # Scan components
        type_counts: dict[str, dict[str, int]] = {}  # type -> {total, covered}
        uncovered_ids: list[str] = []
        total = 0
        covered = 0

        if not components_dir.is_dir():
            return CoverageReport(
                total_components=0,
                covered=0,
                uncovered=0,
                coverage_pct=0.0,
                uncovered_ids=[],
                by_type=[],
            )

        for yaml_file in sorted(components_dir.rglob("*.yaml")):
            data = yaml.safe_load(yaml_file.read_text())
            if not data or not isinstance(data, dict):
                continue
            component_id = data.get("id")
            if not component_id:
                continue

            parts = component_id.split(":", 2)
            comp_type = parts[1] if len(parts) >= 2 else "unknown"

            if comp_type not in type_counts:
                type_counts[comp_type] = {"total": 0, "covered": 0}
            type_counts[comp_type]["total"] += 1
            total += 1

            # Check for matching test files
            patterns = _build_patterns(component_id)
            found = self._find_matching_test(patterns, test_stems, comp_type)
            if found:
                covered += 1
                type_counts[comp_type]["covered"] += 1
            else:
                uncovered_ids.append(component_id)

        pct = (covered / total * 100.0) if total > 0 else 0.0

        by_type = []
        for type_name, counts in sorted(type_counts.items()):
            t = counts["total"]
            c = counts["covered"]
            by_type.append(
                CoverageByType(
                    type_name=type_name,
                    count=t,
                    covered=c,
                    pct=(c / t * 100.0) if t > 0 else 0.0,
                )
            )

        return CoverageReport(
            total_components=total,
            covered=covered,
            uncovered=total - covered,
            coverage_pct=round(pct, 1),
            uncovered_ids=uncovered_ids,
            by_type=by_type,
        )

    def _find_matching_test(self, patterns: list[str], test_stems: list[str], comp_type: str) -> bool:
        """Check if any test file stem matches the component patterns.

        For entity: any test stem containing the entity name.
        For route: test stem containing all route name segments.
        """
        if not patterns:
            return False

        if comp_type == "route":
            # Route: all segments must appear in some test stem
            return any(all(p in stem for p in patterns) for stem in test_stems)

        # Entity/error/other: the last segment (name) must appear
        name = patterns[-1]
        return any(name in stem for stem in test_stems)

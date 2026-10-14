"""Test coverage checker — maps components to test files."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import yaml

from ydk.models.test_gen import CoverageByType, CoverageReport, ManifestCoverage

if TYPE_CHECKING:
    from pathlib import Path


_SKIP_DIRS = {".git", "node_modules", "vendor"}


def _slugify(text: str) -> str:
    """Convert text to lowercase slug fragments for matching."""
    return re.sub(r"[^a-zA-Z0-9]", "_", text).strip("_").lower()


def _build_patterns(component_id: str) -> list[str]:
    """Build filename patterns from a component ID.

    ydk:entity:orders/Order -> ["order"]
    ydk:route:orders/create -> ["order", "create"]
    """
    parts = component_id.split(":", 2)
    name_part = parts[2] if len(parts) == 3 else component_id
    segments = re.split(r"[/\-_]", name_part)
    return [s.lower() for s in segments if s]


class TestCoverageChecker:
    """Check test coverage for YDK components."""

    def check_coverage(
        self,
        components_dir: Path,
        tests_dir: Path,
        test_globs: list[str] | None = None,
        root: Path | None = None,
    ) -> CoverageReport:
        """Scan components and find matching test files.

        For each component, look for test files whose names contain the
        component's namespace/name segments (case-insensitive). ``test_globs``
        (relative to ``root``) selects test files; default is Python under tests_dir.
        """
        test_files = self._collect_test_files(tests_dir, test_globs, root)
        test_stems = [tf.stem.lower() for tf in test_files]
        manifests_raw: list[dict] = []
        req_ids: list[str] = []

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
            if comp_type == "test":
                manifests_raw.append(data)
            elif comp_type == "req":
                req_ids.append(component_id)

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

        manifests, req_cases = self._manifest_coverage(manifests_raw, test_files)

        return CoverageReport(
            total_components=total,
            covered=covered,
            uncovered=total - covered,
            coverage_pct=round(pct, 1),
            uncovered_ids=uncovered_ids,
            by_type=by_type,
            manifests=manifests,
            req_cases=req_cases,
            reqs_without_cases=[r for r in req_ids if r not in req_cases],
        )

    @staticmethod
    def _collect_test_files(tests_dir: Path, test_globs: list[str] | None, root: Path | None) -> list[Path]:
        if test_globs is None:
            return sorted(tests_dir.rglob("test_*.py")) if tests_dir.is_dir() else []
        base = root if root is not None else tests_dir.parent
        found: dict[Path, None] = {}
        for pattern in test_globs:
            try:
                matches = sorted(base.glob(pattern))
            except (NotImplementedError, ValueError):
                continue  # invalid glob (absolute/empty): ignore
            for f in matches:
                rel = f.relative_to(base).parts
                if f.is_file() and not (set(rel) & _SKIP_DIRS) and rel[:2] != (".ydk", "worktrees"):
                    found[f] = None
        return list(found)

    @staticmethod
    def _is_implemented(manifest_id: str, target: str, case: str, contents: list[tuple[Path, str]]) -> bool:
        marker = re.compile(re.escape(f"{manifest_id}#{case}") + r"(?![\w-])")
        go_run = re.compile(r't\.Run\(\s*"' + re.escape(case) + '"')
        go_func = re.compile(r"^func Test" + re.escape(target) + r"\w*\(", re.MULTILINE) if target else None
        for path, text in contents:
            if marker.search(text):
                return True
            if go_func is not None and path.suffix == ".go":
                for m in go_func.finditer(text):
                    nxt = text.find("\nfunc ", m.end())
                    body = text[m.end() : nxt if nxt != -1 else len(text)]
                    if go_run.search(body):
                        return True
        return False

    def _manifest_coverage(
        self, manifests_raw: list[dict], test_files: list[Path]
    ) -> tuple[list[ManifestCoverage], dict[str, list[str]]]:
        contents = [(f, f.read_text(encoding="utf-8", errors="replace")) for f in test_files]
        result: list[ManifestCoverage] = []
        req_cases: dict[str, list[str]] = {}
        for data in manifests_raw:
            manifest_id = data["id"]
            target = str(data.get("target") or "").rsplit("/", 1)[-1].replace(".", "")
            cov = ManifestCoverage(manifest_id=manifest_id, level=str(data.get("level") or ""))
            for case in data.get("cases") or []:
                if not isinstance(case, dict) or not case.get("name"):
                    continue
                name = str(case["name"])
                if self._is_implemented(manifest_id, target, name, contents):
                    cov.implemented.append(name)
                else:
                    cov.missing.append(name)
                reqs = case.get("req") or []
                for req in [reqs] if isinstance(reqs, str) else reqs:
                    req_cases.setdefault(str(req), []).append(f"{manifest_id}#{name}")
            result.append(cov)
        return result, req_cases

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

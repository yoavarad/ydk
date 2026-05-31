"""Layer A deterministic linker — validates references between manifests and narratives."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import yaml

from odk.models.component import LinkerResult

if TYPE_CHECKING:
    from pathlib import Path

    from odk.core.component_registry import ComponentRegistry

_NARRATIVE_REF_PATTERN = re.compile(r"\[odk:[a-zA-Z0-9_-]+:[a-zA-Z0-9/_.-]+\]")
_CROSS_REF_PATTERN = re.compile(r"odk:[a-zA-Z0-9_-]+:[a-zA-Z0-9/_.-]+")


class ComponentLinker:
    """Deterministic reference linker (Layer A).

    Scans narrative markdown files for [odk:...] references and validates
    that every reference resolves to a real component file. Also validates
    cross-references within component manifests.
    """

    def __init__(self, registry: ComponentRegistry, narratives_dir: Path) -> None:
        self._registry = registry
        self._narratives_dir = narratives_dir

    def scan_narratives(self) -> list[tuple[Path, list[str]]]:
        """Find all [odk:...] references in markdown files under narratives_dir."""
        results: list[tuple[Path, list[str]]] = []
        if not self._narratives_dir.is_dir():
            return results

        for md_file in sorted(self._narratives_dir.rglob("*.md")):
            content = md_file.read_text()
            refs: list[str] = []
            for match in _NARRATIVE_REF_PATTERN.finditer(content):
                ref_id = match.group()[1:-1]
                refs.append(ref_id)
            if refs:
                results.append((md_file, refs))
        return results

    def validate_references(self) -> LinkerResult:
        """Check every ref resolves, find orphans."""
        known_ids = self._discover_all_ids()
        narrative_refs = self._collect_narrative_refs()
        manifest_refs = self._collect_manifest_refs(known_ids)

        all_refs = narrative_refs | manifest_refs
        undefined: list[str] = sorted(ref for ref in all_refs if ref not in known_ids)
        all_referenced = narrative_refs | manifest_refs
        orphaned: list[str] = sorted(cid for cid in known_ids if cid not in all_referenced)
        valid: list[str] = sorted(ref for ref in all_refs if ref in known_ids)
        broken_cross: list[str] = self.validate_cross_refs()

        return LinkerResult(
            undefined_refs=undefined,
            orphaned_components=orphaned,
            broken_cross_refs=broken_cross,
            valid_refs=valid,
        )

    def validate_cross_refs(self) -> list[str]:
        """Check refs WITHIN component manifests resolve to existing components."""
        known_ids = self._discover_all_ids()
        broken: list[str] = []

        if not self._registry._components_dir.is_dir():
            return broken

        for yaml_file in self._registry._components_dir.rglob("*.yaml"):
            data = yaml.safe_load(yaml_file.read_text())
            if not data or not isinstance(data, dict):
                continue
            component_id = data.get("id", "")
            content = yaml_file.read_text()
            for match in _CROSS_REF_PATTERN.finditer(content):
                ref_id = match.group()
                if ref_id == component_id:
                    continue
                if ref_id.startswith("odk:schema:"):
                    continue
                if ref_id not in known_ids:
                    broken.append(f"{component_id} -> {ref_id}")
        return sorted(broken)

    def _discover_all_ids(self) -> set[str]:
        """Discover all component IDs from the components directory."""
        ids: set[str] = set()
        if not self._registry._components_dir.is_dir():
            return ids

        for yaml_file in self._registry._components_dir.rglob("*.yaml"):
            data = yaml.safe_load(yaml_file.read_text())
            if data and isinstance(data, dict) and "id" in data:
                ids.add(data["id"])
        return ids

    def _collect_narrative_refs(self) -> set[str]:
        """Collect all odk:... refs from narrative markdown files."""
        refs: set[str] = set()
        scan_results = self.scan_narratives()
        for _path, path_refs in scan_results:
            refs.update(path_refs)
        return refs

    def _collect_manifest_refs(self, known_ids: set[str]) -> set[str]:
        """Collect all cross-references from component manifests."""
        refs: set[str] = set()
        if not self._registry._components_dir.is_dir():
            return refs

        for yaml_file in self._registry._components_dir.rglob("*.yaml"):
            data = yaml.safe_load(yaml_file.read_text())
            if not data or not isinstance(data, dict):
                continue
            component_id = data.get("id", "")
            content = yaml_file.read_text()
            for match in _CROSS_REF_PATTERN.finditer(content):
                ref_id = match.group()
                if ref_id != component_id and not ref_id.startswith("odk:schema:"):
                    refs.add(ref_id)
        return refs

"""Spec evolution engine — orchestrates the change lifecycle."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path

from ydk.core.delta_parser import apply_operations_to_spec, parse_delta_directory
from ydk.models.change import (
    ArchiveResult,
    ArtifactStatus,
    ChangeInfo,
    ChangeMode,
    ChangeStatus,
    DeltaOperation,
)

_REQUIRED_ARTIFACTS: dict[str, list[str]] = {
    "small": ["proposal.md", "delta-specs", "tasks.md"],
    "major": ["proposal.md", "delta-specs", "design.md", "tasks.md"],
}

_PROPOSAL_TEMPLATE = """# {name}

## Why

<!-- What problem does this change solve? -->

## What

<!-- What is being changed? -->

## Scope

### IN

-

### OUT

-
"""

_DESIGN_TEMPLATE = """# {name} — Design

## Approach

<!-- Technical approach -->

## Trade-offs

<!-- What alternatives were considered and why this approach was chosen -->
"""

_TASKS_TEMPLATE = """# {name} — Tasks

- [ ]
"""


class SpecEvolutionEngine:
    """Orchestrates the spec evolution lifecycle: propose, track, archive."""

    def propose(self, name: str, mode: str, project_root: Path) -> ChangeInfo:
        """Create a new change proposal directory with templates."""
        change_mode = ChangeMode(mode)
        change_dir = project_root / "docs" / "changes" / name

        if change_dir.exists():
            msg = f"Change already exists: {name}"
            raise FileExistsError(msg)

        change_dir.mkdir(parents=True)
        (change_dir / "delta-specs").mkdir()

        info = ChangeInfo(name=name, mode=change_mode, status=ChangeStatus.ACTIVE)

        (change_dir / ".change.yaml").write_text(
            yaml.dump(info.model_dump(mode="json"), default_flow_style=False, sort_keys=False)
        )
        (change_dir / "proposal.md").write_text(_PROPOSAL_TEMPLATE.format(name=name))
        (change_dir / "tasks.md").write_text(_TASKS_TEMPLATE.format(name=name))

        if change_mode == ChangeMode.MAJOR:
            (change_dir / "design.md").write_text(_DESIGN_TEMPLATE.format(name=name))

        return info

    def list_changes(self, project_root: Path, status: str = "all") -> list[ChangeInfo]:
        """List changes filtered by status."""
        results: list[ChangeInfo] = []

        changes_dir = project_root / "docs" / "changes"
        if changes_dir.is_dir():
            results.extend(self._scan_changes_dir(changes_dir, ChangeStatus.ACTIVE))

        if status in ("archived", "all"):
            archive_dir = changes_dir / "archive"
            if archive_dir.is_dir():
                for child in sorted(archive_dir.iterdir()):
                    if child.is_dir():
                        results.extend(self._scan_changes_dir(child, ChangeStatus.ARCHIVED, single=True))

        if status == "active":
            results = [c for c in results if c.status == ChangeStatus.ACTIVE]
        elif status == "archived":
            results = [c for c in results if c.status == ChangeStatus.ARCHIVED]

        return results

    def get_change_status(self, name: str, project_root: Path) -> ArtifactStatus:
        """Check which artifacts exist for a change."""
        change_dir = self._find_change_dir(name, project_root)
        mode = self._read_change_mode(change_dir)
        required = _REQUIRED_ARTIFACTS.get(mode, _REQUIRED_ARTIFACTS["small"])

        present: list[str] = []
        for artifact in required:
            path = change_dir / artifact
            if path.exists():
                if path.is_dir():
                    has_content = any(path.iterdir())
                    if has_content:
                        present.append(artifact)
                else:
                    present.append(artifact)

        missing = [a for a in required if a not in present]
        return ArtifactStatus(present=present, required=required, missing=missing)

    def archive(self, name: str, project_root: Path) -> ArchiveResult:
        """Archive a change: apply deltas to canonical specs, move to archive."""
        change_dir = self._find_change_dir(name, project_root)
        delta_dir = change_dir / "delta-specs"
        specs_dir = project_root / "docs" / "specs"

        operations = parse_delta_directory(delta_dir)
        modified_files = self._apply_deltas(operations, specs_dir)

        today = datetime.now().strftime("%Y-%m-%d")
        archive_dir = project_root / "docs" / "changes" / "archive" / f"{today}-{name}"
        archive_dir.parent.mkdir(parents=True, exist_ok=True)
        change_dir.rename(archive_dir)

        yaml_path = archive_dir / ".change.yaml"
        if yaml_path.exists():
            data = yaml.safe_load(yaml_path.read_text())
            data["status"] = "archived"
            yaml_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

        return ArchiveResult(
            operations_applied=len(operations),
            target_files_modified=sorted(set(modified_files)),
            archive_path=str(archive_dir.relative_to(project_root)),
        )

    def diff(self, name: str, project_root: Path) -> list[DeltaOperation]:
        """Preview what archive would do without applying."""
        change_dir = self._find_change_dir(name, project_root)
        return parse_delta_directory(change_dir / "delta-specs")

    def _find_change_dir(self, name: str, project_root: Path) -> Path:
        """Locate the change directory by name."""
        change_dir = project_root / "docs" / "changes" / name
        if change_dir.is_dir():
            return change_dir
        msg = f"Change not found: {name}"
        raise FileNotFoundError(msg)

    def _read_change_mode(self, change_dir: Path) -> str:
        """Read the mode from .change.yaml."""
        yaml_path = change_dir / ".change.yaml"
        if yaml_path.exists():
            data = yaml.safe_load(yaml_path.read_text())
            return str(data.get("mode", "small"))
        return "small"

    def _scan_changes_dir(
        self, directory: Path, expected_status: ChangeStatus, *, single: bool = False
    ) -> list[ChangeInfo]:
        """Scan a directory for .change.yaml files and build ChangeInfo objects."""
        results: list[ChangeInfo] = []
        if single:
            yaml_path = directory / ".change.yaml"
            if yaml_path.exists():
                info = self._load_change_info(yaml_path, expected_status)
                results.append(info)
        else:
            for child in sorted(directory.iterdir()):
                yaml_path = child / ".change.yaml"
                if child.is_dir() and child.name != "archive" and yaml_path.exists():
                    info = self._load_change_info(yaml_path, expected_status)
                    results.append(info)
        return results

    def _load_change_info(self, yaml_path: Path, expected_status: ChangeStatus) -> ChangeInfo:
        """Load a ChangeInfo from a .change.yaml file."""
        data = yaml.safe_load(yaml_path.read_text())
        return ChangeInfo(
            name=data.get("name", yaml_path.parent.name),
            mode=ChangeMode(data.get("mode", "small")),
            status=ChangeStatus(data.get("status", expected_status.value)),
            created_at=data.get("created_at", ""),
        )

    def _apply_deltas(self, operations: list[DeltaOperation], specs_dir: Path) -> list[str]:
        """Apply delta operations to canonical spec files. Returns list of modified filenames."""
        grouped: dict[str, list[DeltaOperation]] = {}
        for op in operations:
            grouped.setdefault(op.target_file, []).append(op)

        modified: list[str] = []
        for target_file, ops in grouped.items():
            target_name = target_file if target_file.endswith(".md") else f"{target_file}.md"
            spec_path = specs_dir / target_name

            if spec_path.exists():
                content = spec_path.read_text()
            else:
                spec_path.parent.mkdir(parents=True, exist_ok=True)
                content = f"# {spec_path.stem}\n"

            new_content = apply_operations_to_spec(content, ops)
            spec_path.write_text(new_content)
            modified.append(target_name)

        return modified

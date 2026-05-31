"""Catalog backend — local filesystem implementation for browsing, installing, and publishing."""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import yaml

from odk.models.catalog import CatalogItem, CatalogManifest

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("odk.catalog")


# Tag-to-install-directory mapping
_TAG_INSTALL_DIRS: dict[str, str] = {
    "ignition-pack": "ignition-packs",
    "verification": "verifications",
    "spec-reviewers": "spec-reviewers",
    "component-schemas": "schemas",
}


@runtime_checkable
class CatalogBackend(Protocol):
    """Protocol for catalog backends (local, remote, etc.)."""

    def search(self, query: str, tags: list[str] | None = None) -> list[CatalogItem]:
        """Search catalog for items matching query and optional tag filters."""
        ...

    def get(self, name: str, version: str | None = None) -> CatalogItem | None:
        """Find a single catalog item by name, optionally pinned to a version."""
        ...

    def install(self, name: str, version: str | None, project_root: Path) -> None:
        """Install a catalog item into a project's .odk/ directories."""
        ...

    def list_installed(self, project_root: Path) -> list[CatalogItem]:
        """List all catalog items installed in a project."""
        ...

    def publish(self, item_path: Path) -> None:
        """Validate and publish a catalog item to the local catalog."""
        ...


def _load_manifest(item_dir: Path) -> CatalogManifest | None:
    """Load and parse a catalog.yaml from an item directory."""
    manifest_path = item_dir / "catalog.yaml"
    if not manifest_path.exists():
        return None
    try:
        data = yaml.safe_load(manifest_path.read_text())
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return CatalogManifest(**data)
    except Exception:
        return None


def _matches_query(manifest: CatalogManifest, query: str, tags: list[str] | None) -> bool:
    """Check whether a manifest matches a keyword query and tag filters."""
    query_lower = query.lower()
    # Match against name, description, and tags
    text_match = query_lower in manifest.name.lower() or query_lower in manifest.description.lower()
    if not text_match:
        text_match = any(query_lower in t.lower() for t in manifest.tags)
    # Also check README if present — but keep it lightweight for keyword search
    if not text_match:
        return False
    if tags:
        return all(t in manifest.tags for t in tags)
    return True


class LocalCatalogBackend:
    """Reads from ~/.odk/catalog/, the package built-in catalog, and project .odk/catalog/."""

    def __init__(self, catalog_dir: Path | None = None, *, include_builtin: bool = True) -> None:
        from pathlib import Path as _Path

        self._catalog_dir = catalog_dir or _Path.home() / ".odk" / "catalog"
        # Built-in catalog shipped with the odk package
        self._builtin_catalog_dir = _Path(__file__).parent.parent / "catalog" if include_builtin else None

    def _iter_items(self) -> list[tuple[Path, CatalogManifest]]:
        """Iterate over all catalog item directories that have valid manifests.

        Scans both the package built-in catalog and the user catalog (~/.odk/catalog/).
        If the same item name exists in both, the package (built-in) version takes precedence.
        """
        seen_names: set[str] = set()
        results: list[tuple[Path, CatalogManifest]] = []

        # Built-in catalog first (takes precedence)
        if self._builtin_catalog_dir is not None and self._builtin_catalog_dir.exists():
            for child in sorted(self._builtin_catalog_dir.iterdir()):
                if not child.is_dir():
                    continue
                manifest = _load_manifest(child)
                if manifest is not None:
                    seen_names.add(manifest.name)
                    results.append((child, manifest))

        # User catalog second (only items not already found in built-in)
        if self._catalog_dir.exists():
            for child in sorted(self._catalog_dir.iterdir()):
                if not child.is_dir():
                    continue
                manifest = _load_manifest(child)
                if manifest is not None and manifest.name not in seen_names:
                    seen_names.add(manifest.name)
                    results.append((child, manifest))

        return results

    def search(self, query: str, tags: list[str] | None = None) -> list[CatalogItem]:
        """Search the catalog for items matching query and optional tag filters."""
        results: list[CatalogItem] = []
        for item_dir, manifest in self._iter_items():
            if _matches_query(manifest, query, tags):
                results.append(
                    CatalogItem(
                        name=manifest.name,
                        version=manifest.version,
                        tags=manifest.tags,
                        path=item_dir,
                    )
                )
        return results

    def get(self, name: str, version: str | None = None) -> CatalogItem | None:
        """Find a catalog item by exact name."""
        for item_dir, manifest in self._iter_items():
            if manifest.name == name:
                if version is not None and manifest.version != version:
                    continue
                return CatalogItem(
                    name=manifest.name,
                    version=manifest.version,
                    tags=manifest.tags,
                    path=item_dir,
                )
        return None

    def check_uninstalled_deps(self, name: str, version: str | None, project_root: Path) -> list[str]:
        """Return names of referenced deps that are not yet installed in the project."""
        item = self.get(name, version)
        if item is None:
            return []

        manifest = _load_manifest(item.path)
        if manifest is None:
            return []

        # Collect all referenced dependency names
        referenced: list[str] = [ref.name for ref in manifest.verification_sets]
        referenced.extend(ref.name for ref in manifest.spec_reviewers)
        referenced.extend(ref.name for ref in manifest.component_schemas)

        if not referenced:
            return []

        # Check which are already installed
        installed_items = self.list_installed(project_root)
        installed_names = {i.name for i in installed_items}

        return [r for r in referenced if r not in installed_names]

    def install(self, name: str, version: str | None, project_root: Path) -> None:
        """Install a catalog item into a project's .odk/ directories based on tags."""
        item = self.get(name, version)
        if item is None:
            msg = f"Catalog item '{name}' not found"
            raise ValueError(msg)

        odk_dir = project_root / ".odk"
        odk_dir.mkdir(parents=True, exist_ok=True)

        # Determine install location based on tags
        installed = False
        for tag in item.tags:
            if tag in _TAG_INSTALL_DIRS:
                dest = odk_dir / _TAG_INSTALL_DIRS[tag] / item.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item.path, dest)
                installed = True

        if not installed:
            # Default: copy to .odk/catalog-installed/<name>
            dest = odk_dir / "catalog-installed" / item.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item.path, dest)

        # Record in .odk/catalog-lock.yaml
        self._record_installed(project_root, item)

    def _record_installed(self, project_root: Path, item: CatalogItem) -> None:
        """Record an installed item in .odk/catalog-lock.yaml."""
        lock_path = project_root / ".odk" / "catalog-lock.yaml"
        lock_data: dict[str, object] = {}
        if lock_path.exists():
            raw = yaml.safe_load(lock_path.read_text())
            if isinstance(raw, dict):
                lock_data = raw

        installed_list: list[dict[str, object]] = []
        raw_installed = lock_data.get("installed")
        if isinstance(raw_installed, list):
            for elem in raw_installed:
                if isinstance(elem, dict):
                    entry: dict[str, object] = {str(k): v for k, v in elem.items()}
                    installed_list.append(entry)

        # Remove existing entry for same name
        installed_list = [e for e in installed_list if isinstance(e, dict) and e.get("name") != item.name]
        installed_list.append({"name": item.name, "version": item.version, "tags": item.tags})
        lock_data["installed"] = installed_list
        lock_path.write_text(yaml.dump(lock_data, default_flow_style=False, sort_keys=False))

    def list_installed(self, project_root: Path) -> list[CatalogItem]:
        """List all catalog items recorded in the project's catalog-lock.yaml."""
        lock_path = project_root / ".odk" / "catalog-lock.yaml"
        if not lock_path.exists():
            return []
        raw = yaml.safe_load(lock_path.read_text())
        if not isinstance(raw, dict):
            return []
        installed_list = raw.get("installed", [])
        if not isinstance(installed_list, list):
            return []
        results: list[CatalogItem] = []
        for entry in installed_list:
            if not isinstance(entry, dict) or "name" not in entry:
                continue
            results.append(
                CatalogItem(
                    name=entry["name"],
                    version=entry.get("version", "0.0.0"),
                    tags=entry.get("tags", []),
                    path=project_root / ".odk",  # approximate
                )
            )
        return results

    def uninstall(self, name: str, project_root: Path) -> bool:
        """Remove a catalog item from the project. Returns True if found and removed."""
        lock_path = project_root / ".odk" / "catalog-lock.yaml"
        if not lock_path.exists():
            return False
        raw = yaml.safe_load(lock_path.read_text())
        if not isinstance(raw, dict):
            return False
        installed_list = raw.get("installed", [])
        if not isinstance(installed_list, list):
            return False

        # Find the item to get its tags
        item_entry: dict[str, object] | None = None
        for entry in installed_list:
            if isinstance(entry, dict) and entry.get("name") == name:
                item_entry = entry
                break
        if item_entry is None:
            return False

        # Remove installed directories
        tags = item_entry.get("tags", [])
        odk_dir = project_root / ".odk"
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, str) and tag in _TAG_INSTALL_DIRS:
                    dest = odk_dir / _TAG_INSTALL_DIRS[tag] / name
                    if dest.exists():
                        shutil.rmtree(dest)

        default_dest = odk_dir / "catalog-installed" / name
        if default_dest.exists():
            shutil.rmtree(default_dest)

        # Update lock file
        raw["installed"] = [e for e in installed_list if not (isinstance(e, dict) and e.get("name") == name)]
        lock_path.write_text(yaml.dump(raw, default_flow_style=False, sort_keys=False))
        return True

    def publish(self, item_path: Path) -> None:
        """Validate a catalog item and copy it to the local catalog."""
        manifest = _load_manifest(item_path)
        if manifest is None:
            msg = f"No valid catalog.yaml found in {item_path}"
            raise ValueError(msg)

        # Required files check
        required = ["catalog.yaml", "README.md"]
        for fname in required:
            if not (item_path / fname).exists():
                msg = f"Missing required file: {fname} in {item_path}"
                raise ValueError(msg)

        # Run publish checks if defined
        for check in manifest.publish_checks:
            if check.command:
                result = subprocess.run(
                    check.command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=item_path,
                )
                if result.returncode != 0:
                    msg = f"Publish check '{check.name}' failed: {result.stderr or result.stdout}"
                    raise ValueError(msg)

        # Copy to catalog directory
        dest = self._catalog_dir / manifest.name
        self._catalog_dir.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(item_path, dest)

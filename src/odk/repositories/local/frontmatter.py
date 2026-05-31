"""YAML frontmatter parsing, rendering, and shared file-update helpers.

All local repositories (tasks, stories, epics) store items as markdown files
with YAML frontmatter.  The ``update_file_status`` and ``append_comment``
helpers extract the duplicated read-modify-write patterns so each repository
no longer re-implements them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path

    from odk.repositories.local.manifest import Manifest


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Split markdown into (frontmatter_dict, body_content)."""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            fm = yaml.safe_load(parts[1])
            if fm is None:
                fm = {}
            body = parts[2].strip()
            return fm, body
    return {}, content


def render_frontmatter(data: dict, body: str) -> str:
    """Combine frontmatter dict + body into markdown."""
    fm_str = yaml.dump(data, default_flow_style=False, sort_keys=False)
    return f"---\n{fm_str}---\n\n{body}"


# ---------------------------------------------------------------------------
# Shared helpers for update_status / add_comment across local repos
# ---------------------------------------------------------------------------


def update_file_status(
    file_path: Path,
    item_id: str,
    status: str,
    manifest: Manifest,
    manifest_key: str,
) -> None:
    """Update status in both the frontmatter file and the manifest.

    Parameters
    ----------
    file_path:
        Path to the markdown file (e.g. ``.odk/tasks/T-001.md``).
    item_id:
        The identifier (``T-001``, ``S-001``, ``E-001``).
    status:
        New status string.
    manifest:
        The Manifest instance managing the index.
    manifest_key:
        Top-level manifest key (``"tasks"``, ``"stories"``, ``"epics"``).
    """
    content = file_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)
    fm["status"] = status
    fm["updated"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    file_path.write_text(render_frontmatter(fm, body), encoding="utf-8")

    data = manifest.load()
    if item_id in data.get(manifest_key, {}):
        data[manifest_key][item_id]["status"] = status
        manifest.save(data)


def append_comment(
    file_path: Path,
    comment: str,
    *,
    timestamp_suffix: str = "",
) -> None:
    """Append a timestamped entry to the Activity Log section of a markdown file.

    Parameters
    ----------
    file_path:
        Path to the markdown file.
    comment:
        The comment text.
    timestamp_suffix:
        Extra text appended to the timestamp heading (e.g. ``" (UTC)"``).
    """
    content = file_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"\n### {now}{timestamp_suffix}\n{comment}\n"
    body = body + entry

    fm["updated"] = now
    file_path.write_text(render_frontmatter(fm, body), encoding="utf-8")

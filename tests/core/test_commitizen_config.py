"""Tests for the [tool.commitizen] release configuration in pyproject.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _cz() -> dict:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["tool"]["commitizen"]


def test_changelog_updated_on_bump() -> None:
    cz = _cz()
    assert cz["update_changelog_on_bump"] is True
    assert cz["changelog_file"] == "CHANGELOG.md"
    assert cz["changelog_incremental"] is True


def test_uv_lock_refreshed_and_staged_before_bump_commit() -> None:
    hooks = _cz()["pre_bump_hooks"]
    assert "uv lock" in hooks
    assert hooks.index("git add uv.lock") > hooks.index("uv lock")


def test_branch_bump_does_not_leave_a_tag() -> None:
    hooks = _cz()["post_bump_hooks"]
    assert any("git','tag','-d'" in h and "CZ_POST_CURRENT_TAG_VERSION" in h for h in hooks)


def test_changelog_exists_with_sections_per_release() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    # Only these tags are reachable from the v1.6.0 history; the rest were squashed away.
    for version in ("1.6.0", "1.5.1", "1.3.0", "1.1.0"):
        assert f"## v{version}" in text
    assert "### Feat" in text
    assert "### Fix" in text

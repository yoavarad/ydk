"""Guard commitizen bump hooks against `uv run` re-syncing mid-release on Windows."""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _cz() -> dict:
    with PYPROJECT.open("rb") as f:
        return tomllib.load(f)["tool"]["commitizen"]


def test_uv_run_hooks_use_no_sync() -> None:
    cz = _cz()
    hooks = cz.get("pre_bump_hooks", []) + cz.get("post_bump_hooks", [])
    offenders = [h for h in hooks if h.startswith("uv run") and "--no-sync" not in h]
    assert offenders == []


def test_post_bump_hook_deletes_tag() -> None:
    hooks = _cz().get("post_bump_hooks", [])
    assert any("git" in h and "tag" in h and "-d" in h and "CZ_POST_CURRENT_TAG_VERSION" in h for h in hooks)

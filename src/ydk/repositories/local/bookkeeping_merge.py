"""Deterministic three-way merge for YDK bookkeeping files.

Parallel task branches all write ``.ydk/manifest.yaml`` and ``.ydk/tasks/*.md``.
These helpers merge such files without an LLM so sibling PRs don't conflict:

- mapping keys are unioned; each field is merged three-way against base
- a key deleted on one side is dropped unless the other side modified it
- ``status`` conflicts resolve to the most advanced status
- ``last_*_id`` counter conflicts resolve to the max
- list conflicts resolve to an ordered union (ours first)
- any other conflicting scalar keeps ours
- markdown bodies keep ours plus lines only theirs added
"""

from __future__ import annotations

import yaml

from ydk.repositories.local.frontmatter import parse_frontmatter, render_frontmatter

_MISSING = object()

_STATUS_RANK = {
    "open": 0,
    "blocked": 1,
    "in-progress": 2,
    "in-review": 3,
    "done": 4,
    "closed": 4,
}


def _merge(base: object, ours: object, theirs: object, key: str = "") -> object:
    if ours == theirs or theirs == base:
        return ours
    if ours == base:
        return theirs
    if isinstance(ours, dict) and isinstance(theirs, dict):
        return _merge_dicts(base if isinstance(base, dict) else {}, ours, theirs)
    if isinstance(ours, list) and isinstance(theirs, list):
        return [*ours, *(item for item in theirs if item not in ours)]
    if key == "status":
        rank_o = _STATUS_RANK.get(str(ours), -1)
        rank_t = _STATUS_RANK.get(str(theirs), -1)
        return theirs if rank_t > rank_o else ours
    if key.startswith("last_") and isinstance(ours, int) and isinstance(theirs, int):
        return max(ours, theirs)
    return ours


def _merge_dicts(base: dict, ours: dict, theirs: dict) -> dict:
    merged: dict = {}
    for key in [*ours, *(k for k in theirs if k not in ours)]:
        b = base.get(key, _MISSING)
        o = ours.get(key, _MISSING)
        t = theirs.get(key, _MISSING)
        if o is _MISSING:
            if t != b:
                merged[key] = t
        elif t is _MISSING:
            if o != b:
                merged[key] = o
        else:
            merged[key] = _merge(b, o, t, str(key))
    return merged


def merge_manifest(base: dict, ours: dict, theirs: dict) -> dict:
    """Three-way merge of parsed manifest dicts."""
    return _merge_dicts(base, ours, theirs)


def _merge_body(base: str, ours: str, theirs: str) -> str:
    if ours == theirs or theirs == base:
        return ours
    if ours == base:
        return theirs
    base_lines = set(base.splitlines())
    ours_lines = ours.splitlines()
    added = [line for line in theirs.splitlines() if line not in base_lines and line not in ours_lines]
    return "\n".join([*ours_lines, *added])


def merge_task_file(base: str, ours: str, theirs: str) -> str:
    """Three-way merge of a markdown file with YAML frontmatter."""
    fm_b, body_b = parse_frontmatter(base)
    fm_o, body_o = parse_frontmatter(ours)
    fm_t, body_t = parse_frontmatter(theirs)
    body = _merge_body(body_b, body_o, body_t)
    if not (fm_o or fm_t):
        return body
    return render_frontmatter(_merge_dicts(fm_b, fm_o, fm_t), body)


def merge_text(path: str, base: str, ours: str, theirs: str) -> str:
    """Merge bookkeeping file contents, dispatching on ``path``.

    Raises ``ValueError`` for unsupported paths and ``yaml.YAMLError`` for
    unparseable YAML.
    """
    if path.endswith("manifest.yaml"):
        b, o, t = (yaml.safe_load(text) or {} for text in (base, ours, theirs))
        if not (isinstance(b, dict) and isinstance(o, dict) and isinstance(t, dict)):
            msg = f"Manifest is not a mapping: {path}"
            raise ValueError(msg)
        merged = merge_manifest(b, o, t)
        return yaml.dump(merged, default_flow_style=False, sort_keys=False)
    if path.endswith(".md"):
        return merge_task_file(base, ours, theirs)
    msg = f"Unsupported bookkeeping file: {path}"
    raise ValueError(msg)

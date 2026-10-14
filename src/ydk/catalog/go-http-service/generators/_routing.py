"""Go 1.22 ServeMux pattern validation: syntax and conflict detection.

Mirrors net/http's rules (routing pattern.go): two patterns conflict when they match a
common request and neither is more specific. ServeMux panics at startup on a conflict,
so the generator rejects them up front.
"""

from __future__ import annotations

import re

EQUIVALENT, MORE_GENERAL, MORE_SPECIFIC, DISJOINT, OVERLAPS = (
    "equivalent",
    "moreGeneral",
    "moreSpecific",
    "disjoint",
    "overlaps",
)
_INVERSE = {MORE_GENERAL: MORE_SPECIFIC, MORE_SPECIFIC: MORE_GENERAL}
_WILDCARD = re.compile(r"^\{([A-Za-z_][A-Za-z0-9_]*)(\.\.\.)?\}$")

# A segment is ("lit", text), ("wild", ""), ("multi", "") or ("lit", "/") for the {$} end anchor.
Segment = tuple[str, str]


def parse_path(path: str) -> list[Segment]:
    """Segments of a ServeMux path pattern; raises ValueError with the reason when invalid."""
    if not path.startswith("/"):
        msg = "must start with '/'"
        raise ValueError(msg)
    parts = path[1:].split("/")
    segments: list[Segment] = []
    names: set[str] = set()
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if part == "{$}":
            if not last:
                msg = "{$} must be the last segment"
                raise ValueError(msg)
            segments.append(("lit", "/"))
        elif "{" in part or "}" in part:
            match = _WILDCARD.match(part)
            if not match:
                msg = f"segment {part!r} must be a whole wildcard like {{name}} or {{name...}}"
                raise ValueError(msg)
            name, multi = match.groups()
            if name in names:
                msg = f"duplicate wildcard name {name!r}"
                raise ValueError(msg)
            names.add(name)
            if multi and not last:
                msg = f"{{{name}...}} must be the last segment"
                raise ValueError(msg)
            segments.append(("multi", "") if multi else ("wild", ""))
        elif part == "" and last:
            segments.append(("multi", ""))  # trailing slash matches the whole subtree
        else:
            segments.append(("lit", part))
    return segments


def _combine(r1: str, r2: str) -> str:
    if r1 == EQUIVALENT:
        return r2
    if r1 == DISJOINT:
        return DISJOINT
    if r1 == OVERLAPS:
        return DISJOINT if r2 == DISJOINT else OVERLAPS
    if r2 == EQUIVALENT:
        return r1
    if r2 == _INVERSE[r1]:
        return OVERLAPS
    return r2


def _compare_segments(x: Segment, y: Segment) -> str:
    if x[0] == "multi" and y[0] == "multi":
        return EQUIVALENT
    if x[0] == "multi":
        return MORE_GENERAL
    if y[0] == "multi":
        return MORE_SPECIFIC
    if x[0] == "wild" and y[0] == "wild":
        return EQUIVALENT
    if x[0] == "wild":
        return DISJOINT if y[1] == "/" else MORE_GENERAL
    if y[0] == "wild":
        return DISJOINT if x[1] == "/" else MORE_SPECIFIC
    return EQUIVALENT if x[1] == y[1] else DISJOINT


def _compare_paths(p1: list[Segment], p2: list[Segment]) -> str:
    multi1, multi2 = p1[-1][0] == "multi", p2[-1][0] == "multi"
    if len(p1) != len(p2) and not multi1 and not multi2:
        return DISJOINT
    rel = EQUIVALENT
    n = min(len(p1), len(p2))
    for x, y in zip(p1[:n], p2[:n], strict=True):
        rel = _combine(rel, _compare_segments(x, y))
        if rel == DISJOINT:
            return rel
    if len(p1) == len(p2):
        return rel
    if len(p1) < len(p2) and multi1:
        return _combine(rel, MORE_GENERAL)
    if len(p2) < len(p1) and multi2:
        return _combine(rel, MORE_SPECIFIC)
    return DISJOINT


def _compare_methods(m1: str, m2: str) -> str:
    if m1 == m2:
        return EQUIVALENT
    if (m1, m2) == ("GET", "HEAD"):
        return MORE_GENERAL  # a GET pattern also serves HEAD
    if (m1, m2) == ("HEAD", "GET"):
        return MORE_SPECIFIC
    return DISJOINT


def conflicts(method1: str, path1: list[Segment], method2: str, path2: list[Segment]) -> bool:
    """True when ServeMux would refuse to register both patterns."""
    mrel = _compare_methods(method1, method2)
    if mrel == DISJOINT:
        return False
    return _combine(mrel, _compare_paths(path1, path2)) in (EQUIVALENT, OVERLAPS)

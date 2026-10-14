"""Unit tests for go-http-service's ServeMux pattern rules (generators/_routing.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "src/ydk/catalog/go-http-service/generators/_routing.py"
_spec = importlib.util.spec_from_file_location("go_http_service_routing", _PATH)
assert _spec is not None
assert _spec.loader is not None
routing = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(routing)


def _conflict(a: str, b: str) -> bool:
    m1, p1 = a.split(" ", 1)
    m2, p2 = b.split(" ", 1)
    return routing.conflicts(m1, routing.parse_path(p1), m2, routing.parse_path(p2))


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("GET /a", "GET /a"),  # duplicate
        ("GET /a/{x}", "GET /a/{y}"),  # same shape, different names
        ("GET /items/{id}/parts", "GET /items/special/{p}"),  # overlap, neither more specific
        ("HEAD /items/{x}", "GET /{y}/special"),  # GET covers HEAD
        ("GET /{$}", "GET /{$}"),
    ],
)
def test_conflicting_patterns(a: str, b: str) -> None:
    assert _conflict(a, b)
    assert _conflict(b, a)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("GET /a/{x}", "GET /a/b"),  # literal more specific
        ("GET /a/{x...}", "GET /a/b"),  # multi more general
        ("GET /a/{x...}", "GET /a/b/c"),
        ("GET /{x}", "GET /{$}"),  # {$} only matches "/", a wildcard never matches empty
        ("GET /{x...}", "GET /{$}"),  # multi more general than the end anchor
        ("GET /a", "GET /a/b/{x...}"),  # different lengths, shorter one not multi
        ("POST /items/{x}", "GET /{y}/special"),  # different methods
        ("GET /a/{x}", "HEAD /a/{x}"),  # HEAD more specific than GET
        ("GET /a/", "GET /a/b"),  # trailing slash is a subtree
    ],
)
def test_compatible_patterns(a: str, b: str) -> None:
    assert not _conflict(a, b)
    assert not _conflict(b, a)


@pytest.mark.parametrize(
    "path",
    ["no-slash", "/a/{x}y", "/a/{bad-name}", "/a/{x...}/b", "/{$}/a", "/a/{x}/{x}", "/a/{x"],
)
def test_invalid_paths(path: str) -> None:
    with pytest.raises(ValueError, match=r"."):
        routing.parse_path(path)


def test_segments() -> None:
    assert routing.parse_path("/a/{x}/{rest...}") == [("lit", "a"), ("wild", ""), ("multi", "")]
    assert routing.parse_path("/{$}") == [("lit", "/")]
    assert routing.parse_path("/a/") == [("lit", "a"), ("multi", "")]

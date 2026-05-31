#!/usr/bin/env python3
"""
Generator: navigation-config
Generates navigation configuration and ROUTES constants from page components.

Input:  ODK_COMPONENTS_PAGE
Output: src/shared/config/navigation.ts

Deferred-safe: prints [] and exits 0 when ODK_COMPONENTS_PAGE is missing.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _context.naming import to_camel
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def _derive_route_name(segments: list[str], params: list[str]) -> str:
    """Derive a camelCase property name for this route."""
    if not params:
        return "list"
    # Strip dynamic segments to find the semantic suffix
    static_segments = [s for s in segments[1:] if not s.startswith("[") and not s.startswith("{")]
    if static_segments:
        return to_camel(static_segments[-1])
    return "detail"


def _build_route_value(route: str, params: list[str]) -> str:
    """Build a TypeScript route value: string literal or arrow function."""
    if not params:
        return f"'{route}'"
    # Build template literal with ${param} substitutions
    ts_route = re.sub(r"\[([^\]]+)\]|\{([^}]+)\}", lambda m: f"${{{m.group(1) or m.group(2)}}}", route)
    param_sig = ", ".join(f"{p}: number | string" for p in params)
    return f"({param_sig}) => `{ts_route}`"


def _build_route_groups(pages: list[dict]) -> list[dict]:
    """
    Build ROUTES groups from page definitions.

    /strategies          -> strategies.list = '/strategies'
    /strategies/[id]     -> strategies.detail = (id: number | string) => `/strategies/${id}`
    /strategies/[id]/code -> strategies.code = (id: number | string) => `/strategies/${id}/code`
    """
    groups: dict[str, list[dict]] = {}
    for page in pages:
        # Use "route" field; fall back to "path" for backward compatibility
        route = page.get("route") or page.get("path", "")
        if not route:
            continue
        route = "/" + route.lstrip("/")
        segments = [s for s in route.split("/") if s]
        if not segments:
            continue

        # First non-dynamic segment is the group key
        group_key = to_camel(segments[0])
        params = re.findall(r"\[([^\]]+)\]|\{([^}]+)\}", route)
        params = [p[0] or p[1] for p in params]
        route_name = _derive_route_name(segments, params)
        route_value = _build_route_value(route, params)

        groups.setdefault(group_key, []).append(
            {
                "name": route_name,
                "value": route_value,
            }
        )

    return [{"key": key, "routes": routes} for key, routes in sorted(groups.items())]


def main() -> None:
    pages_path = os.environ.get("ODK_COMPONENTS_PAGE", "")
    if not pages_path or not Path(pages_path).exists():
        print(json.dumps([]))
        return

    # ODK passes a plain YAML list of page components
    pages = yaml.safe_load(Path(pages_path).read_text(encoding="utf-8")) or []
    if isinstance(pages, dict):
        pages = pages.get("pages", [])

    nav_items = []
    for page in pages:
        # Use "route" field; fall back to "path" for backward compatibility
        route = page.get("route") or page.get("path", "")
        title = page.get("title", "")

        # Skip dynamic route pages from top-level nav
        if "[" in route or "{" in route:
            continue

        if title and route:
            nav_items.append({"label": title, "href": "/" + route.lstrip("/")})

    route_groups = _build_route_groups(pages)

    templates_dir = Path(__file__).parent.parent / "templates" / "shared"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("navigation.ts.j2")
    content = template.render(nav_items=nav_items, route_groups=route_groups).rstrip() + "\n"

    output = [{"path": "navigation.ts", "content": content}]
    print(json.dumps(output))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Generator: page-scaffolding
Generates the 3-tier scaffold + test stub for each page from page components.

  Tier 1:  src/app/{route}/page.tsx              — thin Next.js routing shell
  Tier 2:  src/_pages/{page-id}/index.tsx        — smart container with Suspense
  Tier 2b: src/_pages/{page-id}/hooks/use{Name}Page.ts  — data hook stub
  Tier 3:  src/_pages/{page-id}/__tests__/{Name}Page.test.tsx  — empty test stub

Input:  ODK_COMPONENTS_PAGE
Output: paths relative to output_dir (src/_pages/ by default, shell relative to project root)

Deferred-safe: prints [] and exits 0 when component data is missing.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _context.naming import to_kebab, to_pascal
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def _derive_page_id(page: dict) -> str:
    """Derive a page identifier from an ODK page component."""
    component_id = page.get("id", "")
    if component_id and "/" in component_id:
        return component_id.rsplit("/", 1)[1]
    if component_id and ":" in component_id:
        return component_id.split(":")[-1]
    return component_id or page.get("name", "")


def _route_to_app_path(route: str) -> str:
    """Convert a page route like /strategies/[id] to Next.js app dir path."""
    r = route.lstrip("/")
    return r if r else ""


def _build_page_context(page: dict) -> dict:
    page_id = _derive_page_id(page)
    route = page.get("route", page.get("path", page_id or "/"))
    title = page.get("title", to_pascal(page_id.replace("-", "_")))
    page_name = to_pascal(page_id.replace("-", "_"))
    component_name = f"{page_name}Page"

    widgets = page.get("widgets", [])
    primary_query = page.get("primary_query", "")
    queries = page.get("queries", [primary_query] if primary_query else [])

    sdk_import = f"import {{ {queries[0]} }} from '@/shared/api/generated/sdk.gen'" if queries else ""
    query_key_base = page_id.split("-")[0] if page_id else "root"
    # Derive camelCase domain for typed query key factory (getApiWidgets -> widgets)
    if queries:
        _q = queries[0]
        # Strip common prefixes: getApi, postApi, etc.
        _stripped = re.sub(r"^(get|post|put|patch|delete)Api", "", _q)
        query_key_domain = _stripped[0].lower() + _stripped[1:] if _stripped else query_key_base
    else:
        query_key_domain = query_key_base
    query_key = f"queryKeys.{query_key_domain}.list()"
    query_fn = f"() => {queries[0]}()" if queries else "() => Promise.resolve(null)"

    # Hook imports from mutations/queries
    hook_imports: list[str] = []
    for mutation in page.get("mutations", []):
        if isinstance(mutation, str):
            hook_name = f"use{to_pascal(mutation.replace('-', '_'))}"
            domain = to_kebab(mutation.split("-")[0]) if "-" in mutation else mutation
            hook_imports.append(f"import {{ {hook_name} }} from '@/shared/hooks/{domain}'")

    app_route_dir = _route_to_app_path(route)

    return {
        "page_id": page_id,
        "page_name": page_name,
        "component_name": component_name,
        "title": title,
        "route": route,
        "app_route_dir": app_route_dir,
        "widgets": widgets,
        "sdk_import": sdk_import,
        "query_key": query_key,
        "query_fn": query_fn,
        "hook_imports": hook_imports,
        "has_queries": bool(queries),
    }


def main() -> None:
    pages_path = os.environ.get("ODK_COMPONENTS_PAGE", "")
    if not pages_path or not Path(pages_path).exists():
        # Deferred — not an error; page components may not be authored yet
        print(
            "Warning: ODK_COMPONENTS_PAGE not set or file missing — page-scaffolding deferred.",
            file=sys.stderr,
        )
        print(json.dumps([]))
        return

    # ODK passes a plain YAML list of page components
    pages = yaml.safe_load(Path(pages_path).read_text(encoding="utf-8")) or []
    if isinstance(pages, dict):
        pages = pages.get("pages", [])

    templates_dir = Path(__file__).parent.parent / "templates" / "pages"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    output = []
    for page in pages:
        ctx = _build_page_context(page)
        if not ctx["page_id"]:
            continue

        # Tier 1: App Router shell (output_dir is src/pages/, so ../ reaches src/, then app/)
        shell_content = env.get_template("page-shell.tsx.j2").render(**ctx).rstrip() + "\n"
        shell_path = f"../app/{ctx['app_route_dir']}/page.tsx" if ctx["app_route_dir"] else "../app/page.tsx"
        output.append({"path": shell_path, "content": shell_content})

        # Tier 2: Smart container
        container_content = env.get_template("page-container.tsx.j2").render(**ctx).rstrip() + "\n"
        output.append({"path": f"{ctx['page_id']}/index.tsx", "content": container_content})

        # Tier 2b: Data hook
        hook_content = env.get_template("page-hook.ts.j2").render(**ctx).rstrip() + "\n"
        output.append(
            {
                "path": f"{ctx['page_id']}/hooks/use{ctx['page_name']}Page.ts",
                "content": hook_content,
            }
        )

        # Tier 3: Test stub
        test_content = "\n".join(
            [
                "// Generated by ODK ignition",
                f"// ODK-TODO: implement page tests for '{ctx['page_id']}'",
                "import { render } from '@testing-library/react'",
                f"import {{ {ctx['component_name']} }} from '../index'",
                "",
                f"describe('{ctx['component_name']}', () => {{",
                "  it('renders without crashing', () => {",
                "    // TODO: provide required providers (QueryClient, Router)",
                f"    // render(<{ctx['component_name']} />)",
                "  })",
                "})",
                "",
            ]
        )
        output.append(
            {
                "path": f"{ctx['page_id']}/__tests__/{ctx['component_name']}.test.tsx",
                "content": test_content,
            }
        )

    print(json.dumps(output))


if __name__ == "__main__":
    main()

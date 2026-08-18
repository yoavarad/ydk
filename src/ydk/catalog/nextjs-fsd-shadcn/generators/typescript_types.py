#!/usr/bin/env python3
"""
Generator: typescript-types
Read OpenAPI components.schemas, group by domain, emit
src/entities/{domain}/model/types.ts re-exporting from Hey API generated SDK.

Input:  YDK_ARTIFACT_OPENAPI (path to openapi.json)
Output: {domain}/model/types.ts per inferred domain (path relative to output_dir)

Deferred: if the spec file does not exist yet, prints [] and exits 0.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _context.naming import to_snake
from jinja2 import Environment, FileSystemLoader, StrictUndefined

# Suffixes stripped before domain inference
_SCHEMA_SUFFIXES = (
    "Response",
    "Request",
    "Create",
    "Update",
    "Delete",
    "List",
    "Result",
    "Payload",
    "Body",
    "Dto",
)


def _infer_domain(schema_name: str) -> str:
    """
    Infer the FSD domain (snake_case) from an OpenAPI schema name.

    StrategyRunResponse -> base=StrategyRun -> first_word=Strategy -> domain=strategy
    BacktestResult      -> base=Backtest    -> first_word=Backtest  -> domain=backtest
    """
    base = schema_name
    for suffix in _SCHEMA_SUFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix):
            base = base[: -len(suffix)]
            break
    # Split PascalCase and take the first word as the domain
    snake = to_snake(base)
    return snake.split("_")[0]


def main() -> None:
    openapi_path = os.environ.get("YDK_ARTIFACT_OPENAPI", "")
    if not openapi_path or not Path(openapi_path).exists():
        # Deferred — spec not generated yet; this is not an error
        print(
            "Warning: YDK_ARTIFACT_OPENAPI not set or file missing — typescript-types deferred.",
            file=sys.stderr,
        )
        print(json.dumps([]))
        return

    spec = json.loads(Path(openapi_path).read_text(encoding="utf-8"))
    schemas: dict[str, object] = spec.get("components", {}).get("schemas", {})

    if not schemas:
        print(json.dumps([]))
        return

    # Group schema names by domain
    groups: dict[str, list[str]] = {}
    for name in schemas:
        domain = _infer_domain(name)
        groups.setdefault(domain, []).append(name)

    # Set up Jinja2
    templates_dir = Path(__file__).parent.parent / "templates" / "entities"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("types.ts.j2")

    output = []
    openapi_source = Path(openapi_path).name  # just the filename in the comment
    for domain, names in sorted(groups.items()):
        context = {
            "domain": domain,
            "imports": sorted(names),
            "extra_types": [],
            "openapi_source": openapi_source,
        }
        content = template.render(**context).rstrip() + "\n"
        output.append({"path": f"{domain}/model/types.ts", "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

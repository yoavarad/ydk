#!/usr/bin/env python3
"""Generator: config-loader -- internal/config from the ydk:crosscut env-var table (or ydk:config)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _go_common import comment, emit, go_ident, go_string, load, render

_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def _cells(line: str) -> list[str]:
    return [c.strip().strip("`").strip() for c in line.strip().strip("|").split("|")]


def parse_env_table(spec: str) -> list[dict]:
    """Rows of a markdown table whose header has an 'Env var' column."""
    lines = [ln for ln in spec.splitlines() if ln.strip().startswith("|")]
    if not lines:
        return []
    header = [c.lower() for c in _cells(lines[0])]
    if "env var" not in header:
        return []
    col = {name: header.index(name) for name in ("env var", "required", "default", "rule") if name in header}
    rows = []
    for line in lines[1:]:
        cells = _cells(line)
        if not cells or set("".join(cells)) <= set("-: "):
            continue
        name = cells[col["env var"]] if col["env var"] < len(cells) else ""
        if not _ENV_NAME.match(name):
            continue

        def cell(key: str, cells: list[str] = cells) -> str:
            return cells[col[key]] if key in col and col[key] < len(cells) else ""

        default = cell("default")
        # Only literal single-token defaults; prose like 'system roots' or '<X>' templates are dropped.
        if default in ("-", "") or re.search(r"[\s<>()]", default):
            default = ""
        rows.append(
            {
                "name": name,
                "name_lit": go_string(name),
                "field": go_ident(name.lower()),
                "required": cell("required").lower().startswith("yes"),
                "default_lit": go_string(default),
                "rule": comment(cell("rule"), 100),
            }
        )
    return rows


def main() -> None:
    env_vars: list[dict] = []
    source = "no environment table found"
    for crosscut in load("crosscut"):
        rows = parse_env_table(str(crosscut.get("specification", "")))
        if rows:
            env_vars, source = rows, str(crosscut.get("id"))
            break
    else:
        configs = load("config")
        if configs:
            source = str(configs[0].get("id"))
    emit(
        [{"path": "internal/config/config.go", "content": render("config/config.go.j2", vars=env_vars, source=source)}]
    )


if __name__ == "__main__":
    main()

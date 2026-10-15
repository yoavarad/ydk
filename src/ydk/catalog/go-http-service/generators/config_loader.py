#!/usr/bin/env python3
"""Generator: config-loader -- internal/config from the ydk:crosscut env-var table (or ydk:config)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _go_common import check_unique, comment, emit, go_ident, go_string, load, render

_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def _cells(line: str) -> list[str]:
    return [c.strip().strip("`").strip() for c in line.strip().strip("|").split("|")]


def parse_env_table(spec: str) -> list[dict]:
    """Rows of every markdown table in spec whose header has an 'Env var' column."""
    rows: list[dict] = []
    table: list[str] = []
    for line in [*spec.splitlines(), ""]:
        if line.strip().startswith("|"):
            table.append(line)
        elif table:
            rows.extend(_parse_table(table))
            table = []
    return rows


def _parse_table(lines: list[str]) -> list[dict]:
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
    first: dict[str, tuple[dict, str]] = {}
    sources: list[str] = []
    for crosscut in load("crosscut"):
        cid = str(crosscut.get("id"))
        rows = parse_env_table(str(crosscut.get("specification", "")))
        if rows:
            sources.append(cid)
        for row in rows:
            if row["name"] not in first:  # a var listed in several tables keeps its first definition
                first[row["name"]] = (row, cid)
                env_vars.append(row)
                continue
            prev, prev_id = first[row["name"]]
            if (prev["required"], prev["default_lit"]) != (row["required"], row["default_lit"]):
                sys.stderr.write(
                    f"conflicting definitions of env var {row['name']} in {prev_id} and {cid}; keeping {prev_id}\n"
                )
    check_unique("internal/config Config", [(v["field"], f"env var {v['name']}") for v in env_vars])
    source = ", ".join(sources) or "no environment table found"
    if not sources:
        configs = load("config")
        if configs:
            source = str(configs[0].get("id"))
    emit(
        [{"path": "internal/config/config.go", "content": render("config/config.go.j2", vars=env_vars, source=source)}]
    )


if __name__ == "__main__":
    main()

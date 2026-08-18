#!/usr/bin/env python3
"""Generate DI wiring starter file."""

import json
import os
from pathlib import Path

import yaml


def to_snake(name: str) -> str:
    return "".join(["_" + c.lower() if c.isupper() else c for c in name]).lstrip("_")


def main():
    adapters_path = os.environ.get("YDK_COMPONENTS_ADAPTER", "")
    if not adapters_path or not Path(adapters_path).exists():
        print("[]")
        return

    adata = yaml.safe_load(Path(adapters_path).read_text()) or {}
    adapters = adata.get("adapters", [])

    lines = [
        '"""DI wiring — edit this file to switch adapters.',
        'To switch adapters: update imports below."""',
        "from __future__ import annotations",
        "from sqlalchemy.ext.asyncio import AsyncSession",
        "",
    ]

    # Imports
    for adapter in adapters:
        snake = to_snake(adapter["name"])
        lines.append(f"from src.adapters.database.postgres.{snake} import {adapter['name']}")
    lines.append("from src.adapters.database.postgres.connection import get_session")
    lines.append("")

    # Port imports
    for adapter in adapters:
        pname = adapter.get("implements", "")
        if pname:
            lines.append(f"from src.domain.ports.{to_snake(pname)} import {pname}")
    lines.append("")
    lines.append("")

    # Factory functions
    for adapter in adapters:
        pname = adapter.get("implements", "")
        suffix = "repository" if "Repository" in adapter["name"] else "service"
        base = to_snake(adapter["name"]).replace("_repository", "").replace("_service", "")
        func_name = f"get_{base}_{suffix}"
        ret_type = pname if pname else adapter["name"]
        lines.append(f"def {func_name}(session: AsyncSession = get_session()) -> {ret_type}:")
        lines.append(f"    return {adapter['name']}(session)")
        lines.append("")

    print(json.dumps([{"path": "wiring.py", "content": "\n".join(lines)}]))


if __name__ == "__main__":
    main()

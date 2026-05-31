#!/usr/bin/env python3
"""Generate FastAPI router stubs from ODK route components"""

import json
import os
import re
from pathlib import Path

import yaml


def to_snake(name: str) -> str:
    return "".join(["_" + c.lower() if c.isupper() else c for c in name]).lstrip("_")


def path_to_func(method: str, path: str) -> str:
    parts = [p for p in path.split("/") if p and not p.startswith("{")]
    return f"{method.lower()}_{'_'.join(parts)}" if parts else f"{method.lower()}_root"


def generate_router(tag: str, endpoints: list) -> str:
    lines = [
        "from __future__ import annotations",
        "from fastapi import APIRouter, Depends, HTTPException, status",
        "",
        f'router = APIRouter(prefix="/{tag}", tags=["{tag}"])',
        "",
    ]
    for ep in endpoints:
        method = ep["method"].lower()
        path = ep["path"]
        use_case = ep.get("maps_to_use_case", "")
        func_name = path_to_func(ep["method"], path)

        # Path params
        path_params = re.findall(r"\{(\w+)\}", path)
        param_str = ", ".join(f"{p}: str" for p in path_params)

        lines.append(f"@router.{method}('{path}', status_code=status.HTTP_200_OK)")
        lines.append(f"async def {func_name}({param_str}) -> dict:")
        if use_case:
            lines.append(f"    # TODO: inject and call {use_case} use case")
        lines.append("    raise NotImplementedError")
        lines.append("")
    return "\n".join(lines)


def main():
    path = os.environ.get("ODK_COMPONENTS_ROUTE", "")
    if not path or not Path(path).exists():
        print("[]")
        return
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    # Group endpoints by first path segment
    groups: dict = {}
    for ep in data if isinstance(data, list) else []:
        tag = [p for p in ep.get("path", "").split("/") if p and not p.startswith("{")]
        tag = tag[0] if tag else "root"
        groups.setdefault(tag, []).append(ep)

    output = []
    for tag, endpoints in groups.items():
        output.append({"path": f"{tag}.py", "content": generate_router(tag, endpoints)})
    print(json.dumps(output))


if __name__ == "__main__":
    main()

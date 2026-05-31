#!/usr/bin/env python3
"""Generate Python ABC port interfaces with NotImplementedError stubs"""

import json
import os
from pathlib import Path

import yaml

TYPE_MAP = {
    "str": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "uuid": "UUID",
    "datetime": "datetime",
    "date": "date",
    "bytes": "bytes",
    "json": "dict",
    "None": "None",
}


def map_type(t: str) -> str:
    t = t.strip()
    if t.startswith("optional[") and t.endswith("]"):
        return f"{map_type(t[9:-1])} | None"
    if t.startswith("list[") and t.endswith("]"):
        return f"list[{map_type(t[5:-1])}]"
    if " | None" in t:
        base = t.replace(" | None", "").strip()
        return f"{map_type(base)} | None"
    return TYPE_MAP.get(t, t)


def generate_port(port: dict) -> str:
    name = port["name"]
    methods = port.get("methods", [])
    imports = {"from __future__ import annotations", "from abc import ABC, abstractmethod"}
    method_lines = []
    PRIMITIVES = {
        "None",
        "str",
        "int",
        "float",
        "bool",
        "dict",
        "list",
        "UUID",
        "datetime",
        "date",
        "bytes",
    }

    for m in methods:
        mname = m["name"]
        args = m.get("args", [])
        returns = map_type(m.get("returns", "None"))
        if "UUID" in returns:
            imports.add("from uuid import UUID")
        if "datetime" in returns:
            imports.add("from datetime import datetime")
        # Add UUID/datetime imports for argument types too
        for a in args:
            mapped_arg = map_type(a.get("type", ""))
            if "UUID" in mapped_arg:
                imports.add("from uuid import UUID")
            if "datetime" in mapped_arg:
                imports.add("from datetime import datetime")
        arg_str = ", ".join(f"{a['name']}: {map_type(a['type'])}" for a in args)
        if arg_str:
            arg_str = ", " + arg_str
        method_lines.append(f"""
    @abstractmethod
    def {mname}(self{arg_str}) -> {returns}:
        raise NotImplementedError""")

    # Entity imports
    for m in methods:
        for a in m.get("args", []):
            t = a.get("type", "")
            if t and t[0].isupper() and t not in PRIMITIVES:
                snake = "".join(["_" + c.lower() if c.isupper() else c for c in t]).lstrip("_")
                imports.add(f"from src.domain.models.{snake} import {t}")
        ret = m.get("returns", "")
        first_token = ret.split()[0] if ret else ""
        if first_token and first_token[0].isupper() and first_token not in PRIMITIVES:
            snake = "".join(["_" + c.lower() if c.isupper() else c for c in first_token]).lstrip("_")
            imports.add(f"from src.domain.models.{snake} import {first_token}")

    import_block = "\n".join(sorted(imports))
    methods_block = "\n".join(method_lines)
    return f"""{import_block}


class {name}(ABC):
{methods_block or "    pass"}
"""


def main():
    path = os.environ.get("ODK_COMPONENTS_CONTRACT", "")
    if not path or not Path(path).exists():
        print("[]")
        return
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    # ODK format: contracts is a list, ports are nested in each contract
    contracts = data if isinstance(data, list) else []
    ports = [port for contract in contracts for port in contract.get("ports", [])]
    output = []
    for port in ports:
        name = port["name"]
        snake = "".join(["_" + c.lower() if c.isupper() else c for c in name]).lstrip("_")
        output.append({"path": f"{snake}.py", "content": generate_port(port)})
    print(json.dumps(output))


if __name__ == "__main__":
    main()

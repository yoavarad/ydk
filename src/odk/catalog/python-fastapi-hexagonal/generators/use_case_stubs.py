#!/usr/bin/env python3
"""Generate use case class stubs with injected ports and NotImplementedError"""

import json
import os
from pathlib import Path

import yaml


def to_snake(name: str) -> str:
    return "".join(["_" + c.lower() if c.isupper() else c for c in name]).lstrip("_")


def map_type(t: str) -> str:
    tmap = {
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
    t = t.strip()
    if t.startswith("optional[") and t.endswith("]"):
        return f"{map_type(t[9:-1])} | None"
    if t.startswith("list["):
        return f"list[{map_type(t[5:-1])}]"
    if " | None" in t:
        return f"{map_type(t.replace(' | None', '').strip())} | None"
    return tmap.get(t, t)


def generate_use_case(uc: dict) -> str:
    name = uc["name"]
    raw_ports = uc.get("ports", [])
    port_names = [p["name"] if isinstance(p, dict) else p for p in raw_ports]
    inp = uc.get("input", {})
    out = uc.get("output", {})
    errors = uc.get("errors", [])

    imports = {"from __future__ import annotations"}
    error_classes = []
    for e in errors:
        ename = e["name"]
        error_classes.append(f"\nclass {ename}(Exception):\n    pass")

    # Port imports
    port_args = []
    for pname in port_names:
        snake = to_snake(pname)
        imports.add(f"from src.domain.ports.{snake} import {pname}")
        attr = f"_{snake.replace('_port', '')}"
        port_args.append((pname, attr, snake))

    # Input/output type imports
    input_fields = inp.get("fields", [])
    output_type = map_type(out.get("type", "None")) if out else "None"
    if "UUID" in output_type:
        imports.add("from uuid import UUID")
    if "datetime" in output_type:
        imports.add("from datetime import datetime")
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
    # Extract entity names from output type (handles list[Task], Task | None, Task, etc.)
    import re as _re

    entity_names = _re.findall(r"\b([A-Z][A-Za-z0-9]+)\b", output_type)
    for ename in entity_names:
        if ename not in PRIMITIVES:
            snake_t = to_snake(ename)
            imports.add(f"from src.domain.models.{snake_t} import {ename}")
    for f in input_fields:
        t = map_type(f.get("type", "str"))
        if "UUID" in t:
            imports.add("from uuid import UUID")
        if "datetime" in t:
            imports.add("from datetime import datetime")

    constructor_params = ", ".join(f"{pname.lower()[:4]}: {pname}" for pname, _, _ in port_args) if port_args else ""
    if constructor_params:
        constructor_params = ", " + constructor_params

    exec_params = ", ".join(f"{f['name']}: {map_type(f.get('type', 'str'))}" for f in input_fields)
    if exec_params:
        exec_params = ", " + exec_params

    import_block = "\n".join(sorted(imports))
    errors_block = "\n".join(error_classes)
    indent = "        "
    if port_args:
        assignments = f"\n{indent}".join(f"self.{attr}: {pname} = {pname.lower()[:4]}" for pname, attr, _ in port_args)
    else:
        assignments = "pass"
    init_block = f"""
    def __init__(self{constructor_params}) -> None:
        {assignments}
"""
    return f"""{import_block}
{errors_block}


class {name}:
{init_block}
    def execute(self{exec_params}) -> {output_type}:
        raise NotImplementedError
"""


def main():
    uc_path = os.environ.get("ODK_COMPONENTS_CONTRACT", "")
    if not uc_path or not Path(uc_path).exists():
        print("[]")
        return
    data = yaml.safe_load(Path(uc_path).read_text(encoding="utf-8")) or {}
    output = []
    for uc in data if isinstance(data, list) else []:
        name = uc["name"]
        snake = to_snake(name)
        output.append({"path": f"{snake}.py", "content": generate_use_case(uc)})
    print(json.dumps(output))


if __name__ == "__main__":
    main()

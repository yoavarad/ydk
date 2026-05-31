#!/usr/bin/env python3
"""Generate Pydantic v2 domain entity models from ODK entity components."""

import json
import os
import sys
from pathlib import Path

# Add generators dir to path for _context imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _context.naming import derive_name, iter_fields

TYPE_MAP = {
    "string": "str",
    "str": "str",
    "text": "str",
    "integer": "int",
    "int": "int",
    "bigint": "int",
    "float": "float",
    "boolean": "bool",
    "bool": "bool",
    "uuid": "UUID",
    "UUID": "UUID",
    "Decimal": "Decimal",
    "decimal": "Decimal",
    "datetime": "datetime",
    "date": "date",
    "bytes": "bytes",
    "json": "dict",
    "enum": "str",
}


def map_type(t: str) -> str:
    t = t.strip()
    if t.startswith("optional[") and t.endswith("]"):
        inner = t[9:-1]
        return f"{map_type(inner)} | None"
    if t.startswith("list[") and t.endswith("]"):
        inner = t[5:-1]
        return f"list[{map_type(inner)}]"
    if t.startswith("dict[") and t.endswith("]"):
        inner = t[5:-1]
        k, v = inner.split(",", 1)
        return f"dict[{map_type(k.strip())}, {map_type(v.strip())}]"
    if " | None" in t:
        base = t.replace(" | None", "").strip()
        return f"{map_type(base)} | None"
    # Handle union types with pipe (e.g. "Decimal|null", "str | null")
    if "|" in t:
        parts = [map_type(p.strip()) for p in t.split("|")]
        return " | ".join(parts)
    # Map "null" to Python None
    if t.lower() == "null":
        return "None"
    return TYPE_MAP.get(t, t)  # EntityName passes through as-is


def needs_import(t: str, imports: set) -> None:
    if "UUID" in t:
        imports.add("from uuid import UUID, uuid4")
    if "Decimal" in t:
        imports.add("from decimal import Decimal")
    if "datetime" in t and "date" not in t.replace("datetime", ""):
        imports.add("from datetime import datetime, timezone")
    if "date" in t and "datetime" not in t:
        imports.add("from datetime import date")
    if "Field" in t:
        imports.add("from pydantic import Field")


def generate_entity(entity: dict) -> str:
    name = derive_name(entity)
    imports = set(["from __future__ import annotations", "from pydantic import BaseModel"])

    field_lines = []
    for fname, fdef in iter_fields(entity):
        ftype = map_type(fdef.get("type", "string"))
        needs_import(ftype, imports)
        required = fdef.get("required", True)
        default = fdef.get("default")

        if default == "uuid4":
            imports.add("from uuid import UUID, uuid4")
            imports.add("from pydantic import Field")
            field_lines.append(f"    {fname}: {ftype} = Field(default_factory=uuid4)")
        elif default == "now":
            imports.add("from datetime import datetime, timezone")
            imports.add("from pydantic import Field")
            field_lines.append(f"    {fname}: {ftype} = Field(default_factory=lambda: datetime.now(timezone.utc))")
        elif fdef.get("auto") and fdef.get("type", "").lower() in ("datetime", "optional[datetime]"):
            imports.add("from datetime import datetime, timezone")
            imports.add("from pydantic import Field")
            field_lines.append(f"    {fname}: {ftype} = Field(default_factory=lambda: datetime.now(timezone.utc))")
        elif default is not None and default != "null":
            field_lines.append(f"    {fname}: {ftype} = {repr(default)}")
        elif "default" in fdef or not required:
            # Explicit default: null or optional field → Python None
            field_lines.append(f"    {fname}: {ftype} = None")
        else:
            field_lines.append(f"    {fname}: {ftype}")

    import_block = "\n".join(sorted(imports))
    fields_block = "\n".join(field_lines) if field_lines else "    pass"

    return f"""{import_block}


class {name}(BaseModel):
{fields_block}
"""


def main():
    entity_path = os.environ.get("ODK_COMPONENTS_ENTITY", "")
    if not entity_path or not Path(entity_path).exists():
        print("[]")
        return

    data = yaml.safe_load(Path(entity_path).read_text(encoding="utf-8")) or {}
    entities = data if isinstance(data, list) else []

    output = []
    for entity in entities:
        name = derive_name(entity)
        content = generate_entity(entity)
        filename = f"{name.lower()}.py"
        output.append({"path": filename, "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

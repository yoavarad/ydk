#!/usr/bin/env python3
"""Generate TypeScript interfaces from YDK entity components"""

import json
import os
from pathlib import Path

import yaml
from _context.naming import derive_name, iter_fields

TS_TYPE_MAP = {
    "str": "string",
    "int": "number",
    "float": "number",
    "bool": "boolean",
    "uuid": "string",
    "datetime": "Date",
    "date": "Date",
    "bytes": "Buffer",
    "json": "Record<string, unknown>",
}


def map_ts(t: str) -> str:
    t = t.strip()
    if t.startswith("optional[") and t.endswith("]"):
        return f"{map_ts(t[9:-1])} | null"
    if t.startswith("list[") and t.endswith("]"):
        return f"{map_ts(t[5:-1])}[]"
    if t.startswith("dict[") and t.endswith("]"):
        inner = t[5:-1]
        k, v = inner.split(",", 1)
        return f"Record<{map_ts(k.strip())}, {map_ts(v.strip())}>"
    if " | None" in t:
        return f"{map_ts(t.replace(' | None', '').strip())} | null"
    return TS_TYPE_MAP.get(t, t)  # EntityName passes through


def generate_entity_ts(entity: dict, all_entities: set) -> str:
    name = derive_name(entity)
    imports = set()
    field_lines = []
    for fname, fdef in iter_fields(entity):
        ftype = map_ts(fdef.get("type", "str"))
        # Import other entity types
        base_type = ftype.replace("[]", "").replace(" | null", "").strip()
        if base_type in all_entities and base_type != name:
            imports.add(f"import type {{ {base_type} }} from './{base_type[0].lower() + base_type[1:]}';")
        optional = not fdef.get("required", True) or "| null" in ftype
        field_lines.append(f"  {fname}{'?' if optional else ''}: {ftype};")

    import_block = "\n".join(sorted(imports))
    fields_block = "\n".join(field_lines)
    return (
        f"""{import_block}

export type {name} = {{
{fields_block}
}};
""".strip()
        + "\n"
    )


def main():
    path = os.environ.get("YDK_COMPONENTS_ENTITY", "")
    if not path or not Path(path).exists():
        print("[]")
        return
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    entities = data if isinstance(data, list) else []
    all_names = {derive_name(e) for e in entities}
    output = []
    for entity in entities:
        name = derive_name(entity)
        fname = name[0].lower() + name[1:] + ".ts"
        output.append({"path": fname, "content": generate_entity_ts(entity, all_names)})
    print(json.dumps(output))


if __name__ == "__main__":
    main()

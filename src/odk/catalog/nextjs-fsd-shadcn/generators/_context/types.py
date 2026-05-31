"""Canonical type → TypeScript type mappings for nextjs-fsd-shadcn generators."""

from __future__ import annotations

# canonical type -> TypeScript type string
CANONICAL_TO_TS: dict[str, str] = {
    "str": "string",
    "int": "number",
    "float": "number",
    "bool": "boolean",
    "uuid": "string",  # UUIDs are strings in JSON
    "datetime": "string",  # ISO-8601 string in JSON
    "date": "string",  # ISO-8601 date string
    "bytes": "string",  # base64-encoded string
    "json": "Record<string, unknown>",
}

# canonical types that are nullable (Optional[...]) — used for import logic
NULLABLE_TYPES: frozenset[str] = frozenset(f"optional[{t}]" for t in CANONICAL_TO_TS)


def map_ts_type(canonical: str) -> str:
    """
    Convert a canonical type string to its TypeScript equivalent.

    Handles:
      - optional[T]   → T | null
      - list[T]       → T[]
      - dict[K, V]    → Record<K, V>
      - bare types    → from CANONICAL_TO_TS (pass-through if unknown)
    """
    t = canonical.strip()
    tl = t.lower()

    if tl.startswith("optional[") and tl.endswith("]"):
        inner = map_ts_type(t[9:-1])
        return f"{inner} | null"

    if tl.startswith("list[") and tl.endswith("]"):
        inner = map_ts_type(t[5:-1])
        # Wrap compound types in parens so `(T | null)[]` is unambiguous
        if " | " in inner:
            return f"({inner})[]"
        return f"{inner}[]"

    if tl.startswith("dict[") and tl.endswith("]"):
        inner = t[5:-1]
        # Split only on the first comma to handle nested generics
        comma_idx = inner.index(",")
        key_ts = map_ts_type(inner[:comma_idx].strip())
        val_ts = map_ts_type(inner[comma_idx + 1 :].strip())
        return f"Record<{key_ts}, {val_ts}>"

    if " | None" in t:
        # Python-style T | None → T | null
        base = t.replace(" | None", "").strip()
        return f"{map_ts_type(base)} | null"

    return CANONICAL_TO_TS.get(tl, t)  # unknown/entity names pass through

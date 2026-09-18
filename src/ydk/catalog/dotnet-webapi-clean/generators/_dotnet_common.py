"""Shared naming and C# type-mapping helpers for dotnet-webapi-clean generators.

Task #103 (sibling, in progress) is building generators/_context/{naming,types,imports}.py
with the pack's canonical C# naming/type helpers. This module is a minimal, self-contained
fallback so this task's generators do not block on that merge. It intentionally uses a
distinct name (not `_context/`) to avoid colliding with that module on merge; once
generators/_context/ lands, callers here can be pointed at it as a follow-up.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

CANONICAL_TO_CSHARP: dict[str, str] = {
    "string": "string",
    "text": "string",
    "integer": "int",
    "int": "int",
    "bigint": "long",
    "decimal": "decimal",
    "float": "double",
    "double": "double",
    "uuid": "Guid",
    "datetime": "DateTime",
    "date": "DateOnly",
    "bool": "bool",
    "boolean": "bool",
}


def to_pascal_case(name: str) -> str:
    """Convert snake_case / kebab-case to PascalCase.

    created_at -> CreatedAt, category-id -> CategoryId, id -> Id
    """
    parts = re.split(r"[_\-]+", name)
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def derive_entity_name(entity: dict) -> str:
    """Derive the entity's PascalCase name from its YDK id or name field.

    "ydk:entity:sample/Item" -> "Item"
    """
    component_id = entity.get("id", "")
    if component_id:
        if "/" in component_id:
            return component_id.rsplit("/", 1)[1]
        parts = component_id.split(":")
        if len(parts) > 1:
            return parts[-1]
    return entity.get("name", "Unknown")


def iter_fields(entity: dict):
    """Yield (field_name, field_def) for each field on an entity component."""
    fields = entity.get("fields", {})
    if isinstance(fields, dict):
        for field_name, field_def in fields.items():
            yield field_name, field_def if isinstance(field_def, dict) else {"type": str(field_def)}
    elif isinstance(fields, list):
        for field in fields:
            yield field.get("name", "unknown"), field


def csharp_type(field: dict) -> str:
    """Map a YDK canonical field type to a C# type, applying nullability.

    A field is treated as nullable when explicitly marked `nullable: true` or
    `required: false` (and it isn't the primary key). Absent either marker, a
    field is treated as required/non-nullable.
    """
    ftype = str(field.get("type", "string")).lower()
    base_type = CANONICAL_TO_CSHARP.get(ftype, "string")
    nullable = bool(field.get("nullable")) or (field.get("required") is False and not field.get("primary_key"))
    return f"{base_type}?" if nullable else base_type


def pluralize(name: str) -> str:
    """Naive English pluralization for DbSet/table names."""
    if name.endswith("y") and len(name) > 1 and name[-2].lower() not in "aeiou":
        return name[:-1] + "ies"
    if name.endswith(("s", "x", "z", "ch", "sh")):
        return name + "es"
    return name + "s"


def project_namespace(default: str = "WebApi") -> str:
    """Derive the root C# namespace from YDK_PROJECT_ROOT's directory name, else default."""
    root = os.environ.get("YDK_PROJECT_ROOT", "")
    if not root:
        return default
    base = Path(root).name
    if not base:
        return default
    pascal = to_pascal_case(re.sub(r"[^0-9A-Za-z]+", "_", base))
    return pascal or default

"""Naming utilities for YDK dotnet-webapi-clean generators."""

from __future__ import annotations

import re

# Root .NET namespace / solution name shared by every generated project in
# this pack (Domain/Application/Infrastructure/Api/Tests all nest under it).
ROOT_NAMESPACE = "WebApiClean"

# C# reserved keywords that need escaping (`@name`) when used as identifiers.
CSHARP_KEYWORDS = frozenset(
    {
        "abstract",
        "as",
        "base",
        "bool",
        "break",
        "byte",
        "case",
        "catch",
        "char",
        "checked",
        "class",
        "const",
        "continue",
        "decimal",
        "default",
        "delegate",
        "do",
        "double",
        "else",
        "enum",
        "event",
        "explicit",
        "extern",
        "false",
        "finally",
        "fixed",
        "float",
        "for",
        "foreach",
        "goto",
        "if",
        "implicit",
        "in",
        "int",
        "interface",
        "internal",
        "is",
        "lock",
        "long",
        "namespace",
        "new",
        "null",
        "object",
        "operator",
        "out",
        "override",
        "params",
        "private",
        "protected",
        "public",
        "readonly",
        "ref",
        "return",
        "sbyte",
        "sealed",
        "short",
        "sizeof",
        "stackalloc",
        "static",
        "string",
        "struct",
        "switch",
        "this",
        "throw",
        "true",
        "try",
        "typeof",
        "uint",
        "ulong",
        "unchecked",
        "unsafe",
        "ushort",
        "using",
        "virtual",
        "void",
        "volatile",
        "while",
    }
)


def to_pascal(name: str) -> str:
    """Convert snake_case, kebab-case, or camelCase to PascalCase.

    strategy_run -> StrategyRun
    strategy-run -> StrategyRun
    strategyRun  -> StrategyRun
    StrategyRun  -> StrategyRun (idempotent)
    """
    if not name:
        return name
    spaced = re.sub(r"[_\-]+", " ", name)
    # Split camelCase/PascalCase runs at lower-to-upper boundaries.
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", spaced)
    words = [w for w in spaced.split(" ") if w]
    return "".join(w[0].upper() + w[1:] for w in words)


def to_camel(name: str) -> str:
    """Convert to camelCase (PascalCase with a lowercase leading character)."""
    pascal = to_pascal(name)
    if not pascal:
        return pascal
    return pascal[0].lower() + pascal[1:]


def derive_name(component: dict) -> str:
    """Derive the PascalCase component name from its YDK id field.

    Parses "ydk:entity:strategy/Strategy" -> "Strategy"
    Parses "ydk:contract:strategy/StrategyService" -> "StrategyService"
    Falls back to component["name"] for legacy data that still has a name field.
    """
    component_id = component.get("id", "")
    if component_id:
        if "/" in component_id:
            raw = component_id.rsplit("/", 1)[1]
        else:
            parts = component_id.split(":")
            raw = parts[-1] if len(parts) > 1 else component_id
        return to_pascal(raw)
    return to_pascal(component.get("name", "Unknown"))


def derive_table_name(entity: dict) -> str:
    """Return the EF Core table name for an entity, deriving from its name if absent.

    YDK schema allows an explicit table_name; if missing, derives by pluralizing
    the PascalCase entity name (EF Core convention: PascalCase, plural table names).
    """
    if "table_name" in entity:
        table_name = entity["table_name"]
        if not isinstance(table_name, str) or not table_name.strip():
            raise ValueError(f"Entity '{derive_name(entity)}' has empty or invalid table_name.")
        return table_name.strip()
    name = derive_name(entity)
    if name.endswith("y") and len(name) > 1 and name[-2].lower() not in "aeiou":
        return name[:-1] + "ies"
    if name.endswith(("s", "x", "z", "ch", "sh")):
        return name + "es"
    return name + "s"


def pk_type(entity: dict) -> str:
    """Return the C# type string for the primary key field. Defaults to 'int'.

    Handles both YDK map-format and legacy list-format fields.
    """
    from .types import CANONICAL_TO_CSHARP

    fields = entity.get("fields", {})
    if isinstance(fields, dict):
        for _field_name, field_def in fields.items():
            if isinstance(field_def, dict) and field_def.get("primary_key"):
                ftype = field_def.get("type", "integer").lower()
                return CANONICAL_TO_CSHARP.get(ftype, "int")
    elif isinstance(fields, list):
        for field in fields:
            if field.get("primary_key"):
                ftype = field.get("type", "int").lower()
                return CANONICAL_TO_CSHARP.get(ftype, "int")
    return "int"


def sanitize_identifier(name: str) -> str:
    """Escape a C# identifier that collides with a reserved keyword using '@'."""
    if name in CSHARP_KEYWORDS:
        return f"@{name}"
    return name


def iter_fields(entity: dict):
    """Iterate over entity fields yielding (field_name, field_def) tuples.

    Works with the YDK map format where fields is a dict keyed by field name.
    Each field_def is guaranteed to be a dict.
    """
    fields = entity.get("fields", {})
    if isinstance(fields, dict):
        for field_name, field_def in fields.items():
            if isinstance(field_def, dict):
                yield field_name, field_def
            else:
                yield field_name, {"type": str(field_def)}
    elif isinstance(fields, list):
        for field in fields:
            yield field.get("name", "unknown"), field

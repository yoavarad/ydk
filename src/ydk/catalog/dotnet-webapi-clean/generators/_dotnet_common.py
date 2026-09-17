"""Shared naming and type-mapping helpers for dotnet-webapi-clean generators.

Self-contained (no dependency on ``generators/_context/``, which is produced by a
parallel task building the Domain layer) so this pack's Application/Infrastructure
generators can run standalone. Mirrors the naming conventions of
``python-fastapi-hexagonal``'s ``_context/naming.py`` where applicable, adapted for
C#/.NET output.
"""

from __future__ import annotations

import re

CANONICAL_TO_CSHARP = {
    "string": "string",
    "str": "string",
    "text": "string",
    "integer": "int",
    "int": "int",
    "bigint": "long",
    "float": "double",
    "double": "double",
    "decimal": "decimal",
    "Decimal": "decimal",
    "boolean": "bool",
    "bool": "bool",
    "uuid": "Guid",
    "UUID": "Guid",
    "datetime": "DateTime",
    "date": "DateOnly",
    "bytes": "byte[]",
    "json": "string",
    "jsonb": "string",
    "enum": "string",
    "any": "object",
    "Any": "object",
    "object": "object",
    "void": "void",
    "None": "void",
    "null": "void",
}


def derive_name(component: dict) -> str:
    """Derive a component's PascalCase name from its YDK id field.

    "ydk:entity:orders/Order" -> "Order"
    "ydk:contract:orders/OrderService" -> "OrderService"
    """
    component_id = component.get("id", "")
    if component_id:
        if "/" in component_id:
            return component_id.rsplit("/", 1)[1]
        parts = component_id.split(":")
        if len(parts) > 1:
            return parts[-1]
    return component.get("name", "Unknown")


def to_pascal(name: str) -> str:
    """snake_case or kebab-case -> PascalCase. get_order -> GetOrder"""
    parts = re.split(r"[_\-]+", name)
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def to_camel(name: str) -> str:
    """PascalCase -> camelCase. OrderRepository -> orderRepository"""
    if not name:
        return name
    return name[0].lower() + name[1:]


def to_camel_param(name: str) -> str:
    """snake_case, kebab-case, or PascalCase -> camelCase param name. order_id -> orderId"""
    return to_camel(to_pascal(name))


def pluralize(name: str) -> str:
    """Simple English pluralization for DbSet property names. Order -> Orders, Category -> Categories."""
    if name.endswith("y") and len(name) > 1 and name[-2].lower() not in "aeiou":
        return name[:-1] + "ies"
    if name.endswith(("s", "x", "z", "ch", "sh")):
        return name + "es"
    return name + "s"


def map_type(t: str) -> str:
    """Map a canonical/entity type string to a C# type.

    Handles list[...] -> IEnumerable<...>, Optional[...]/"X | None" -> "X?",
    and bare entity-reference names (capitalized, not a known primitive) pass
    through unchanged (the entity's own C# class name, e.g. from Domain.Entities).
    """
    t = t.strip()
    if t.lower().startswith("optional[") and t.endswith("]"):
        inner = map_type(t[9:-1])
        return inner if inner.endswith("?") else f"{inner}?"
    if t.lower().startswith("list[") and t.endswith("]"):
        return f"IEnumerable<{map_type(t[5:-1])}>"
    if "|" in t:
        parts = [p.strip() for p in t.split("|")]
        non_none = [p for p in parts if p.lower() not in ("none", "null")]
        if len(non_none) == 1 and len(parts) > 1:
            inner = map_type(non_none[0])
            return inner if inner.endswith("?") else f"{inner}?"
        return " | ".join(map_type(p) for p in parts)
    return CANONICAL_TO_CSHARP.get(t, t)


def pk_field(entity: dict) -> tuple[str, str]:
    """Return (field_name, csharp_type) for the entity's primary key field.

    Falls back to ("Id", "Guid") when no field is marked primary_key, matching
    the ADR's SQLite/EF Core defaults (Guid PKs generated client-side).
    """
    fields = entity.get("fields", {})
    if isinstance(fields, dict):
        for field_name, field_def in fields.items():
            if isinstance(field_def, dict) and field_def.get("primary_key"):
                ftype = str(field_def.get("type", "uuid"))
                return field_name, map_type(ftype)
    elif isinstance(fields, list):
        for field in fields:
            if isinstance(field, dict) and field.get("primary_key"):
                ftype = str(field.get("type", "uuid"))
                return field.get("name", "Id"), map_type(ftype)
    return "Id", "Guid"


def contract_methods(contract: dict) -> list[dict]:
    """Normalize a contract's ``methods`` map into a list of method contexts.

    Each returned dict has: name (PascalCase), task_return (C# Task/Task<T>),
    is_void, params (list of {name, type}).
    """
    methods_raw = contract.get("methods", {})
    methods: list[dict] = []
    if not isinstance(methods_raw, dict):
        return methods

    for method_name, method_def in methods_raw.items():
        method_def = method_def if isinstance(method_def, dict) else {}

        raw_params = method_def.get("params", {}) or {}
        params: list[dict] = []
        if isinstance(raw_params, dict):
            for pname, pval in raw_params.items():
                ptype = pval.get("type", "string") if isinstance(pval, dict) else str(pval)
                params.append({"name": to_camel_param(pname), "type": map_type(ptype)})
        elif isinstance(raw_params, list):
            for p in raw_params:
                ptype = p.get("type", "string")
                params.append({"name": to_camel_param(p.get("name", "value")), "type": map_type(ptype)})

        raw_returns = method_def.get("returns", "void")
        return_type_raw = raw_returns.get("type", "void") if isinstance(raw_returns, dict) else str(raw_returns)
        csharp_return = map_type(return_type_raw)
        is_void = csharp_return == "void"
        task_return = "Task" if is_void else f"Task<{csharp_return}>"

        methods.append(
            {
                "name": to_pascal(method_name),
                "task_return": task_return,
                "is_void": is_void,
                "params": params,
            }
        )
    return methods


def service_and_entity_name(contract: dict) -> tuple[str, str]:
    """Derive (service_name, entity_name) from a contract component.

    "ydk:contract:orders/OrderService" -> ("OrderService", "Order")
    "ydk:contract:orders/Order"        -> ("OrderService", "Order")
    """
    raw_name = derive_name(contract)
    if raw_name.endswith("Service"):
        entity_name = raw_name[: -len("Service")]
        service_name = raw_name
    else:
        entity_name = raw_name
        service_name = raw_name + "Service"
    return service_name, entity_name

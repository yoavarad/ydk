"""Naming utilities for ODK generators."""

from __future__ import annotations

import keyword
import re

PYTHON_KEYWORDS = set(keyword.kwlist)


def to_snake(name: str) -> str:
    """Convert PascalCase to snake_case. StrategyRun → strategy_run"""
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s).lower()


def to_pascal(snake: str) -> str:
    """Convert snake_case to PascalCase. strategy_run → StrategyRun"""
    return "".join(w.capitalize() for w in snake.split("_"))


def derive_name(component: dict) -> str:
    """Derive the component name from its ODK id field.

    Parses "odk:entity:strategy/Strategy" → "Strategy"
    Parses "odk:contract:strategy/StrategyService" → "StrategyService"
    Falls back to component["name"] for legacy data that still has a name field.
    """
    component_id = component.get("id", "")
    if component_id:
        # odk:type:namespace/Name → last segment after /
        if "/" in component_id:
            return component_id.rsplit("/", 1)[1]
        # odk:type:Name → last segment after :
        parts = component_id.split(":")
        if len(parts) > 1:
            return parts[-1]
    # Legacy fallback
    return component.get("name", "Unknown")


def derive_table_name(entity: dict) -> str:
    """Return table_name from entity, deriving from name if absent.

    ODK schema allows explicit table_name; if missing, derives by
    pluralizing + snake_casing the entity name.
    """
    if "table_name" in entity:
        table_name = entity["table_name"]
        if not isinstance(table_name, str) or not table_name.strip():
            raise ValueError(f"Entity '{derive_name(entity)}' has empty or invalid table_name.")
        return table_name.strip()
    # Derive from entity name
    name = derive_name(entity)
    snake = to_snake(name)
    # Simple pluralization
    if snake.endswith("y") and len(snake) > 1 and snake[-2] not in "aeiou":
        return snake[:-1] + "ies"
    if snake.endswith(("s", "x", "z", "ch", "sh")):
        return snake + "es"
    return snake + "s"


# Keep validate_table_name as an alias for backward compat within pack
validate_table_name = derive_table_name


def pk_type(entity: dict) -> str:
    """Return the Python type string for the primary key field. Defaults to 'int'.

    Handles both ODK map-format fields and legacy list-format fields.
    """
    pk_type_map = {
        "int": "int",
        "integer": "int",
        "bigint": "int",
        "uuid": "UUID",
        "UUID": "UUID",
        "str": "str",
        "string": "str",
    }
    fields = entity.get("fields", {})
    if isinstance(fields, dict):
        # ODK map format: {field_name: {type: ..., primary_key: true}}
        for _field_name, field_def in fields.items():
            if isinstance(field_def, dict) and field_def.get("primary_key"):
                ftype = field_def.get("type", "integer").lower()
                return pk_type_map.get(ftype, "int")
    elif isinstance(fields, list):
        # Legacy list format
        for field in fields:
            if field.get("primary_key"):
                ftype = field.get("type", "int").lower()
                return pk_type_map.get(ftype, "int")
    return "int"


def list_filter_params(entity: dict) -> list[dict]:
    """Return indexed non-PK fields as filter parameters for list() methods.

    Handles both ODK map-format and legacy list-format fields.
    Each item: {name, type, default}
    """
    from .types import CANONICAL_TO_PYTHON

    params = []
    fields = entity.get("fields", {})

    if isinstance(fields, dict):
        # ODK map format
        for field_name, field_def in fields.items():
            if not isinstance(field_def, dict):
                continue
            if field_def.get("index") and not field_def.get("primary_key"):
                ftype = field_def.get("type", "string").lower()
                py = CANONICAL_TO_PYTHON.get(ftype, "str")
                if py.endswith("| None"):
                    nullable_py = py
                else:
                    nullable_py = f"{py} | None"
                params.append(
                    {
                        "name": field_name,
                        "type": nullable_py,
                        "default": "None",
                    }
                )
    elif isinstance(fields, list):
        # Legacy list format
        for field in fields:
            if field.get("index") and not field.get("primary_key"):
                ftype = field.get("type", "str").lower()
                py = CANONICAL_TO_PYTHON.get(ftype, "str")
                if py.endswith("| None"):
                    nullable_py = py
                else:
                    nullable_py = f"{py} | None"
                params.append(
                    {
                        "name": field["name"],
                        "type": nullable_py,
                        "default": "None",
                    }
                )
    return params


def has_updated_at(entity: dict) -> bool:
    """Return True if entity has an updated_at timestamp field.

    Handles both ODK map-format and legacy list-format fields.
    """
    fields = entity.get("fields", {})
    if isinstance(fields, dict):
        return "updated_at" in fields
    elif isinstance(fields, list):
        return any(f["name"] == "updated_at" for f in fields)
    return False


def sanitize_module_name(name: str) -> str:
    """Sanitize a module name that collides with a Python reserved word.

    Appends a trailing underscore when the name is a keyword.
    """
    if name in PYTHON_KEYWORDS:
        return f"{name}_"
    return name


def port_module_name(port_name: str) -> str:
    """Return the module file stem for a port class name.

    Strips the trailing ``Port`` suffix before snake-casing so the module
    name matches the file produced by the generator (e.g.
    ``repository_ports`` emits ``strategy_snapshot_repository.py``).

    StrategyRepositoryPort  -> strategy_repository
    NotificationPort        -> notification
    BrokerPort              -> broker
    """
    stem = port_name.removesuffix("Port") if port_name.endswith("Port") else port_name
    return sanitize_module_name(to_snake(stem))


def iter_fields(entity: dict):
    """Iterate over entity fields yielding (field_name, field_def) tuples.

    Works with the ODK map format where fields is a dict keyed by field name.
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
        # Legacy list format fallback
        for field in fields:
            yield field.get("name", "unknown"), field

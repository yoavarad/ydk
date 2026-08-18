"""Import set builders for YDK generators."""

from __future__ import annotations

from .types import SQLALCHEMY_IMPORTS, STDLIB_IMPORTS


def python_imports_for_fields(fields: list[dict] | dict) -> list[str]:
    """
    Build the minimal set of Python stdlib imports needed for entity fields.
    Accepts both YDK map-format (dict) and list-format fields.
    Returns sorted import statements.
    """
    # Normalize to list format
    if isinstance(fields, dict):
        field_list = [{"name": k, **(v if isinstance(v, dict) else {"type": str(v)})} for k, v in fields.items()]
    else:
        field_list = fields

    needed: set[str] = set()
    has_optional = False

    for field in field_list:
        ftype = field.get("type", "string").lower()
        if ftype.startswith("optional["):
            has_optional = True
        imp = STDLIB_IMPORTS.get(ftype)
        if imp:
            needed.add(imp)

    # Always add Optional if any optional field exists
    if has_optional:
        needed.add("from typing import Optional")

    return sorted(needed)


def sqlalchemy_imports_for_fields(fields: list[dict] | dict) -> list[str]:
    """
    Build the minimal set of SQLAlchemy imports needed for entity fields.
    Accepts both YDK map-format (dict) and list-format fields.
    Returns sorted import statements.
    """
    from .types import CANONICAL_TO_SQLALCHEMY

    # Normalize to list format
    if isinstance(fields, dict):
        field_list = [{"name": k, **(v if isinstance(v, dict) else {"type": str(v)})} for k, v in fields.items()]
    else:
        field_list = fields

    needed: set[str] = set()
    needed.add("from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column")

    for field in field_list:
        ftype = field.get("type", "string").lower()
        sa_type, _ = CANONICAL_TO_SQLALCHEMY.get(ftype, ("String", []))
        imp = SQLALCHEMY_IMPORTS.get(sa_type)
        if imp:
            needed.add(imp)

    return sorted(needed)

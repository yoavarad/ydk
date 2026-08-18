#!/usr/bin/env python3
"""
Generator: sqlalchemy-models
Generates SQLAlchemy 2.0 Mapped ORM model files from YDK entity components.
Input: YDK_COMPONENTS_ENTITY
Output: one {entity_snake}.py per entity + base.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add generators dir to path for _context imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _context.naming import derive_name, derive_table_name, iter_fields, sanitize_module_name, to_snake
from _context.types import (
    CANONICAL_TO_SQLALCHEMY,
    SQLALCHEMY_IMPORTS,
    STDLIB_IMPORTS,
)
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def _derive_fk_table(entity_ref: str) -> str:
    """Derive the table name from an entity reference for ForeignKey.

    "Strategy" -> "strategies"
    "ydk:entity:strategies/Strategy" -> "strategies"
    "StrategyPortfolio" -> "strategy_portfolios"
    """
    # Strip YDK ID prefix if present
    name = entity_ref
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    if ":" in name:
        name = name.rsplit(":", 1)[-1]

    # Convert to table name using same logic as derive_table_name
    snake = to_snake(name)
    if snake.endswith("y") and len(snake) > 1 and snake[-2] not in "aeiou":
        return snake[:-1] + "ies"
    if snake.endswith(("s", "x", "z", "ch", "sh")):
        return snake + "es"
    return snake + "s"


def build_col_args(field: dict) -> str:
    """Build the mapped_column(...) argument string for a field."""
    ftype = field.get("type", "string").lower()
    # Strip "|null" or "| null" suffix for SA type lookup (nullability handled by column def)
    base_ftype = ftype
    if "|" in ftype:
        base_ftype = ftype.split("|")[0].strip()
    sa_class, sa_args = CANONICAL_TO_SQLALCHEMY.get(base_ftype, CANONICAL_TO_SQLALCHEMY.get(ftype, ("String", [])))

    # Handle Decimal precision from YDK schema
    if ftype == "decimal" and "precision" in field:
        prec = field["precision"]
        if isinstance(prec, list) and len(prec) == 2:
            sa_args = [f"precision={prec[0]}", f"scale={prec[1]}"]

    parts = []
    if sa_args:
        parts.append(f"{sa_class}({', '.join(sa_args)})")
    else:
        parts.append(f"{sa_class}()")

    # ForeignKey: derive table.column from entity reference
    fk_ref = field.get("foreign_key", "")
    if fk_ref:
        # fk_ref is entity name like "Strategy" — derive table name + .id
        fk_table = _derive_fk_table(fk_ref)
        parts.append(f'ForeignKey("{fk_table}.id")')

    if field.get("primary_key"):
        parts.append("primary_key=True")
    if field.get("primary_key") or field.get("nullable") is False or field.get("required"):
        # PKs and required fields are never null; optional[] types are always nullable
        if not ftype.startswith("optional["):
            parts.append("nullable=False")
    else:
        parts.append("nullable=True")
    if field.get("unique"):
        parts.append("unique=True")
    if field.get("index") and not field.get("primary_key"):
        parts.append("index=True")
    if field.get("generated"):
        ftype_lower = ftype.lower() if isinstance(ftype, str) else ""
        if ftype_lower in ("integer", "bigint", "int"):
            parts.append("autoincrement=True")
    if field.get("default") is not None and field.get("default") != "null":
        default = field["default"]
        if default == "now":
            parts.append("default=lambda: datetime.now(timezone.utc)")
        elif default == "uuid4":
            parts.append("default=uuid4")
        elif isinstance(default, str):
            parts.append(f'server_default="{default}"')
        elif isinstance(default, bool):
            parts.append(f"default={default}")
        elif isinstance(default, (int, float)):
            parts.append(f"default={default}")
    elif "default" in field and (field["default"] is None or field["default"] == "null"):
        # Explicit default: null in YAML → Python None
        parts.append("default=None")
    elif field.get("auto"):
        # YDK auto: true means auto-generate (timestamps)
        if ftype in ("datetime", "optional[datetime]"):
            parts.append("default=lambda: datetime.now(timezone.utc)")

    return ", ".join(parts)


def build_mapped_type(field: dict) -> str:
    """Build the Mapped[...] type annotation for a field."""
    ftype = field.get("type", "string").lower()

    # Type mapping for Mapped annotations (Python 3.10+ X | None syntax)
    TYPE_MAP = {
        "string": "str",
        "str": "str",
        "text": "str",
        "integer": "int",
        "int": "int",
        "float": "float",
        "boolean": "bool",
        "bool": "bool",
        "uuid": "uuid.UUID",
        "UUID": "uuid.UUID",
        "Decimal": "Decimal",
        "decimal": "Decimal",
        "datetime": "datetime",
        "date": "date",
        "bytes": "bytes",
        "json": "dict[str, Any]",
        "enum": "str",
        "null": "None",
        "none": "None",
        "optional[string]": "str | None",
        "optional[str]": "str | None",
        "optional[text]": "str | None",
        "optional[integer]": "int | None",
        "optional[int]": "int | None",
        "optional[float]": "float | None",
        "optional[boolean]": "bool | None",
        "optional[bool]": "bool | None",
        "optional[uuid]": "uuid.UUID | None",
        "optional[UUID]": "uuid.UUID | None",
        "optional[Decimal]": "Decimal | None",
        "optional[datetime]": "datetime | None",
        "optional[date]": "date | None",
        "optional[json]": "dict[str, Any] | None",
        "optional[bytes]": "bytes | None",
        "list[str]": "list[str]",
        "list[string]": "list[str]",
        "list[int]": "list[int]",
        "list[integer]": "list[int]",
    }

    # Handle union types with pipe (e.g. "decimal|null", "str | null")
    if "|" in ftype:
        parts = []
        for part in ftype.split("|"):
            part = part.strip()
            if part in ("null", "none"):
                parts.append("None")
            else:
                parts.append(TYPE_MAP.get(part, "str"))
        return " | ".join(parts)

    return TYPE_MAP.get(ftype, "str")


def build_relationship_context(rel: dict, owner_name: str = "") -> dict:
    """Build relationship context dict for template.

    Args:
        rel: The relationship definition from the entity component.
        owner_name: The name of the entity that owns this relationship (for back_populates).
    """
    # YDK relationships use 'entity' ref; extract the entity name from YDK ID or plain name
    target = rel.get("target", "") or rel.get("entity", "")
    # Strip YDK entity ID prefix if present: "ydk:entity:strategy/Strategy" -> "Strategy"
    if "/" in target:
        target = target.rsplit("/", 1)[-1]
    if ":" in target:
        target = target.rsplit(":", 1)[-1]
    target_model = f"{target}Model"
    # Normalize rel_type: accept both hyphens and underscores
    rel_type = rel.get("type", "many_to_one").replace("-", "_")

    if rel_type == "one_to_many":
        mapped_type = f"list['{target_model}']"
    elif rel_type == "many_to_many":
        mapped_type = f"list['{target_model}']"
    elif rel_type == "one_to_one":
        mapped_type = f"'{target_model} | None'"
    else:  # many_to_one
        mapped_type = f"'{target_model} | None'"

    # Derive back_populates: use explicit back_ref if provided, otherwise derive from owner
    back_ref = rel.get("back_ref", "") or rel.get("back_populates", "")
    if not back_ref and owner_name:
        owner_snake = to_snake(owner_name)
        if rel_type == "many_to_one":
            # This side has the FK; the inverse on target is a collection named after the owner (pluralized)
            # e.g. StrategyPortfolio.strategy -> Strategy.strategy_portfolios
            if owner_snake.endswith("y") and len(owner_snake) > 1 and owner_snake[-2] not in "aeiou":
                back_ref = owner_snake[:-1] + "ies"
            elif owner_snake.endswith(("s", "x", "z")):
                back_ref = owner_snake + "es"
            else:
                back_ref = owner_snake + "s"
        elif rel_type == "one_to_one":
            # This side has the FK; the inverse on target is singular
            # e.g. UserProfile.user -> User.user_profile
            back_ref = owner_snake
        elif rel_type == "one_to_many":
            # This side is the parent; the inverse on target is named after the target (singular)
            back_ref = to_snake(target)

    return {
        "attr_name": rel.get("name", to_snake(target)),
        "mapped_type": mapped_type,
        "target_model": target_model,
        "back_ref": back_ref,
    }


def collect_imports(entity: dict) -> list[str]:
    """Collect all needed imports for a model file."""
    imports: set[str] = set()
    imports.add("from app.core.models.base import Base")

    # Track datetime module members needed — emit one consolidated import line
    dt_names: set[str] = set()
    need_uuid_stdlib = False
    need_decimal = False

    # Iterate fields as YDK map
    for fname, field in iter_fields(entity):
        ftype = field.get("type", "string").lower()
        # Strip "|null" or "| null" for SA type lookup
        base_ftype = ftype.split("|")[0].strip() if "|" in ftype else ftype
        sa_class, _ = CANONICAL_TO_SQLALCHEMY.get(base_ftype, CANONICAL_TO_SQLALCHEMY.get(ftype, ("String", [])))
        if sa_imp := SQLALCHEMY_IMPORTS.get(sa_class):
            imports.add(sa_imp)

        # Accumulate stdlib datetime names; defer uuid to avoid name clash with SA UUID
        if ftype in ("datetime", "optional[datetime]"):
            dt_names.add("datetime")
        elif ftype in ("date", "optional[date]"):
            dt_names.add("date")
        elif ftype in ("uuid", "optional[uuid]", "UUID", "optional[UUID]"):
            need_uuid_stdlib = True
        elif ftype in ("decimal", "optional[decimal]", "Decimal", "optional[Decimal]"):
            need_decimal = True
        elif stdlib_imp := STDLIB_IMPORTS.get(ftype):
            imports.add(stdlib_imp)

        # Default-related imports
        default = field.get("default")
        auto = field.get("auto")
        if default == "now" or (auto and ftype in ("datetime", "optional[datetime]")):
            dt_names.add("datetime")
            dt_names.add("timezone")
        if default == "uuid4":
            imports.add("from uuid import uuid4")

    # Emit single consolidated datetime import
    if dt_names:
        imports.add(f"from datetime import {', '.join(sorted(dt_names))}")

    # UUID stdlib: use uuid.UUID to avoid clash with SA's UUID type
    if need_uuid_stdlib:
        imports.add("import uuid")

    if need_decimal:
        imports.add("from decimal import Decimal")

    # Add ForeignKey import when any field has foreign_key
    for _fname, field in iter_fields(entity):
        if field.get("foreign_key"):
            imports.add("from sqlalchemy import ForeignKey")
            break

    # Add UniqueConstraint / Index imports when composite indexes are defined
    indexes = entity.get("indexes", [])
    needs_unique_constraint = any(isinstance(idx, dict) and idx.get("unique") for idx in indexes)
    needs_index = any(isinstance(idx, dict) and not idx.get("unique") for idx in indexes)
    sa_constraint_symbols: list[str] = []
    if needs_unique_constraint:
        sa_constraint_symbols.append("UniqueConstraint")
    if needs_index:
        sa_constraint_symbols.append("Index")
    if sa_constraint_symbols:
        imports.add(f"from sqlalchemy import {', '.join(sorted(sa_constraint_symbols))}")

    # Build ORM import line — include relationship when entity has explicit relationships
    # OR foreign_key fields (which auto-generate relationships)
    rels = entity.get("relationships", [])
    has_fk = any(field.get("foreign_key") for _fname, field in iter_fields(entity))
    if rels or has_fk:
        imports.add("from sqlalchemy.orm import Mapped, mapped_column, relationship")
    else:
        imports.add("from sqlalchemy.orm import Mapped, mapped_column")

    # Merge same-module imports (e.g. combine multiple "from sqlalchemy import X" lines)
    from collections import defaultdict

    module_symbols: dict[str, list[str]] = defaultdict(list)
    standalone: list[str] = []
    for imp in imports:
        if imp.startswith("from ") and " import " in imp:
            module, syms = imp.split(" import ", 1)
            for sym in syms.split(", "):
                module_symbols[module].append(sym.strip())
        else:
            standalone.append(imp)
    merged: set[str] = set(standalone)
    for module, syms in module_symbols.items():
        merged.add(f"{module} import {', '.join(sorted(set(syms)))}")

    # Sort imports in isort order: stdlib → third-party → first-party
    _third_party_prefixes = ("sqlalchemy", "fastapi", "pydantic", "structlog", "httpx", "jose")
    stdlib = sorted(
        i
        for i in merged
        if not i.startswith("from app.") and not any(i.startswith(f"from {p}") for p in _third_party_prefixes)
    )
    third_party = sorted(i for i in merged if any(i.startswith(f"from {p}") for p in _third_party_prefixes))
    first_party = sorted(i for i in merged if i.startswith("from app."))
    groups = [g for g in [stdlib, third_party, first_party] if g]
    result: list[str] = []
    for i, group in enumerate(groups):
        if i > 0:
            result.append("")
        result.extend(group)
    return result


def _build_table_args(entity: dict) -> list[str]:
    """Build table_args list: UniqueConstraint or Index strings per composite index."""
    indexes = entity.get("indexes", [])
    if not indexes:
        return []
    table_name = derive_table_name(entity)
    args: list[str] = []
    for idx in indexes:
        if not isinstance(idx, dict):
            continue
        # YDK format: {fields: [...], unique: bool, description: ...}
        columns = idx.get("columns", []) or idx.get("fields", [])
        name = idx.get("name", "")
        is_unique = bool(idx.get("unique", False))
        # Strip sort directions (e.g. "closed_at DESC" → "closed_at")
        columns = [c.split()[0] for c in columns]
        # Generate unique index name using table name to avoid collisions
        if not name:
            col_suffix = "_".join(columns)
            if is_unique:
                name = f"uq_{table_name}_{col_suffix}"
            else:
                name = f"ix_{table_name}_{col_suffix}"
        # Render column names as quoted strings: "col1", "col2"
        col_str = ", ".join(f'"{c}"' for c in columns)
        if is_unique:
            args.append(f'UniqueConstraint({col_str}, name="{name}")')
        else:
            args.append(f'Index("{name}", {col_str})')
    return args


def build_entity_context(entity: dict) -> dict:
    """Build the full Jinja2 template context for one entity."""
    fields = []
    for fname, fdef in iter_fields(entity):
        mapped = build_mapped_type(fdef)
        col = build_col_args(fdef)
        fields.append(
            {
                "attr_name": fname,
                "mapped_type": mapped,
                "col_args": col,
                "noqa": "",
            }
        )

    entity_name = derive_name(entity)
    # Collect explicit relationships
    relationships = [build_relationship_context(rel, owner_name=entity_name) for rel in entity.get("relationships", [])]

    # Auto-generate relationships from foreign_key fields that aren't already covered
    existing_targets = {r["target_model"] for r in relationships}
    for fname, fdef in iter_fields(entity):
        fk_ref = fdef.get("foreign_key", "")
        if not fk_ref:
            continue
        # Resolve target entity name from FK reference
        target = fk_ref
        if "/" in target:
            target = target.rsplit("/", 1)[-1]
        if ":" in target:
            target = target.rsplit(":", 1)[-1]
        target_model = f"{target}Model"
        if target_model in existing_targets:
            continue
        # Auto-generate a many-to-one relationship for this FK field
        auto_rel = {
            "entity": target,
            "type": "many-to-one",
            "fk": fname,
        }
        relationships.append(build_relationship_context(auto_rel, owner_name=entity_name))
        existing_targets.add(target_model)

    return {
        "name": derive_name(entity),
        "table_name": derive_table_name(entity),
        "imports": collect_imports(entity),
        "fields": fields,
        "relationships": relationships,
        "table_args": _build_table_args(entity),
    }


def _build_inverse_relationship_map(entities: list[dict]) -> dict[str, list[dict]]:
    """Build a map of inverse relationships for each entity.

    For each entity that has FK relationships pointing to another entity,
    record what the inverse (parent-side) relationship should look like on
    the target entity.

    Returns: {target_entity_name: [{"child_entity": ..., "child_model": ...,
              "attr_name": ..., "back_populates": ...}, ...]}
    """
    inverse_map: dict[str, list[dict]] = {}

    for entity in entities:
        entity_name = derive_name(entity)
        entity_snake = to_snake(entity_name)

        # Check explicit relationships
        for rel in entity.get("relationships", []):
            rel_type = rel.get("type", "many_to_one").replace("-", "_")
            if rel_type not in ("many_to_one", "one_to_one"):
                continue
            target = rel.get("target", "") or rel.get("entity", "")
            if "/" in target:
                target = target.rsplit("/", 1)[-1]
            if ":" in target:
                target = target.rsplit(":", 1)[-1]

            # The back_populates on the child side points to what the child calls the parent
            child_back_populates = rel.get("name", to_snake(target))

            # Determine the collection name on the parent (pluralize the child entity snake)
            attr_name = entity_snake
            if attr_name.endswith("y") and len(attr_name) > 1 and attr_name[-2] not in "aeiou":
                attr_name = attr_name[:-1] + "ies"
            elif attr_name.endswith(("s", "x", "z")):
                attr_name = attr_name + "es"
            else:
                attr_name = attr_name + "s"

            inverse_map.setdefault(target, []).append(
                {
                    "child_entity": entity_name,
                    "child_model": f"{entity_name}Model",
                    "attr_name": attr_name,
                    "back_populates": child_back_populates,
                }
            )

        # Check FK fields that auto-generate relationships
        for _fname, fdef in iter_fields(entity):
            fk_ref = fdef.get("foreign_key", "")
            if not fk_ref:
                continue
            target = fk_ref
            if "/" in target:
                target = target.rsplit("/", 1)[-1]
            if ":" in target:
                target = target.rsplit(":", 1)[-1]

            # Skip if already covered by explicit relationship
            explicit_targets = set()
            for rel in entity.get("relationships", []):
                t = rel.get("target", "") or rel.get("entity", "")
                if "/" in t:
                    t = t.rsplit("/", 1)[-1]
                if ":" in t:
                    t = t.rsplit(":", 1)[-1]
                explicit_targets.add(t)
            if target in explicit_targets:
                continue

            # The child-side relationship attr is named after the target (snake)
            child_back_populates = to_snake(target)

            # Collection name on parent
            attr_name = entity_snake
            if attr_name.endswith("y") and len(attr_name) > 1 and attr_name[-2] not in "aeiou":
                attr_name = attr_name[:-1] + "ies"
            elif attr_name.endswith(("s", "x", "z")):
                attr_name = attr_name + "es"
            else:
                attr_name = attr_name + "s"

            inverse_map.setdefault(target, []).append(
                {
                    "child_entity": entity_name,
                    "child_model": f"{entity_name}Model",
                    "attr_name": attr_name,
                    "back_populates": child_back_populates,
                }
            )

    return inverse_map


def main() -> None:
    entity_path = os.environ.get("YDK_COMPONENTS_ENTITY", "")
    if not entity_path or not Path(entity_path).exists():
        print("Error: YDK_COMPONENTS_ENTITY not set or file not found", file=sys.stderr)
        sys.exit(1)

    entities = yaml.safe_load(Path(entity_path).read_text())
    if not isinstance(entities, list):
        entities = []

    # Set up Jinja2
    templates_dir = Path(__file__).parent.parent / "templates" / "models"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    output = []

    # Generate base.py
    base_template = env.get_template("base.py.j2")
    output.append({"path": "app/core/models/base.py", "content": base_template.render()})

    # Build inverse relationship map (second pass awareness)
    inverse_map = _build_inverse_relationship_map(entities)

    # Generate one file per entity
    model_template = env.get_template("model.py.j2")
    for entity in entities:
        try:
            context = build_entity_context(entity)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        # Add inverse relationships (parent-side) from the inverse map
        entity_name = derive_name(entity)
        inverse_rels = inverse_map.get(entity_name, [])
        existing_attrs = {r["attr_name"] for r in context["relationships"]}
        for inv in inverse_rels:
            if inv["attr_name"] not in existing_attrs:
                context["relationships"].append(
                    {
                        "attr_name": inv["attr_name"],
                        "mapped_type": f"list['{inv['child_model']}']",
                        "target_model": inv["child_model"],
                        "back_ref": inv["back_populates"],
                    }
                )
                existing_attrs.add(inv["attr_name"])

        # Ensure relationship import is present if inverse rels were added
        if inverse_rels and context["relationships"]:
            orm_import_base = "from sqlalchemy.orm import Mapped, mapped_column"
            orm_import_full = "from sqlalchemy.orm import Mapped, mapped_column, relationship"
            if orm_import_base in context["imports"] and orm_import_full not in context["imports"]:
                context["imports"] = [orm_import_full if imp == orm_import_base else imp for imp in context["imports"]]

        snake_name = sanitize_module_name(to_snake(derive_name(entity)))
        content = model_template.render(**context).rstrip() + "\n"
        output.append({"path": f"app/core/models/{snake_name}.py", "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

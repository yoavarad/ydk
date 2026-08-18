#!/usr/bin/env python3
"""
Generator: value-object-stubs
Generate Pydantic BaseModel stubs for types referenced in contracts
that are NOT already covered by entity generators.
Input: YDK contract + entity components
Output: app/core/models/{snake_name}.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Add generators dir to path for _context imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _context.naming import derive_name, to_snake

# Python primitives and builtins that should never become value objects
PRIMITIVES = frozenset(
    {
        "str",
        "int",
        "float",
        "bool",
        "Decimal",
        "list",
        "dict",
        "None",
        "Any",
        "UUID",
        "datetime",
        "date",
        "bytes",
        "tuple",
        "set",
    }
)


def _extract_type_refs(type_str: str) -> set[str]:
    """Extract all capitalized type names from a type string.

    Handles: "list[Order]", "AccountInfo", "str", "Decimal|null", etc.
    Returns only non-primitive uppercase identifiers.
    """
    refs = set()
    # Find all identifiers that start with uppercase
    for match in re.findall(r"\b([A-Z][A-Za-z0-9]+)\b", type_str):
        if match not in PRIMITIVES:
            refs.add(match)
    return refs


def _scan_contracts(contracts: list[dict]) -> set[str]:
    """Scan all contract methods for type references (returns + params)."""
    referenced: set[str] = set()

    for contract in contracts:
        methods = contract.get("methods", {})
        if isinstance(methods, list):
            method_list = methods
        elif isinstance(methods, dict):
            method_list = []
            for _name, mdef in methods.items():
                if isinstance(mdef, dict):
                    method_list.append(mdef)
        else:
            continue

        for method in method_list:
            # Scan returns
            returns = method.get("returns", {})
            if isinstance(returns, dict):
                ret_type = returns.get("type", "")
            elif isinstance(returns, str):
                ret_type = returns
            else:
                ret_type = ""
            if ret_type:
                referenced.update(_extract_type_refs(ret_type))

            # Scan params
            params = method.get("params", {})
            if isinstance(params, dict):
                for _pname, pdef in params.items():
                    if isinstance(pdef, dict):
                        ptype = pdef.get("type", "")
                    else:
                        ptype = str(pdef)
                    if ptype:
                        referenced.update(_extract_type_refs(ptype))
            elif isinstance(params, list):
                for p in params:
                    if isinstance(p, dict):
                        ptype = p.get("type", "")
                        if ptype:
                            referenced.update(_extract_type_refs(ptype))

            # Also scan input (legacy format)
            inp = method.get("input", {})
            if isinstance(inp, dict):
                if "fields" in inp:
                    for field in inp["fields"]:
                        ftype = field.get("type", "")
                        if ftype:
                            referenced.update(_extract_type_refs(ftype))
                else:
                    for _k, v in inp.items():
                        referenced.update(_extract_type_refs(str(v)))
            elif isinstance(inp, list):
                for field in inp:
                    if isinstance(field, dict):
                        ftype = field.get("type", "")
                        if ftype:
                            referenced.update(_extract_type_refs(ftype))

            # Scan output (legacy format)
            out = method.get("output", "")
            if isinstance(out, dict):
                out_type = out.get("type", "")
            elif isinstance(out, str):
                out_type = out
            else:
                out_type = ""
            if out_type:
                referenced.update(_extract_type_refs(out_type))

    return referenced


def _collect_entity_names(entities: list[dict]) -> set[str]:
    """Collect all entity names (these already get model files from sqlalchemy_models)."""
    names: set[str] = set()
    for entity in entities:
        name = derive_name(entity)
        names.add(name)
        # Also add with Model suffix since contracts may reference either form
        if not name.endswith("Model"):
            names.add(f"{name}Model")
    return names


def _collect_entity_fields(entities: list[dict]) -> dict[str, list[dict]]:
    """Build a map of entity name -> list of field dicts from entity components."""
    field_map: dict[str, list[dict]] = {}
    for entity in entities:
        name = derive_name(entity)
        fields = entity.get("fields", entity.get("attributes", []))
        if isinstance(fields, dict):
            fields = [{"name": k, **(v if isinstance(v, dict) else {"type": str(v)})} for k, v in fields.items()]
        if fields:
            field_map[name] = fields
            # Also store without Model suffix
            if name.endswith("Model"):
                field_map[name[: -len("Model")]] = fields
    return field_map


def _infer_fields_from_contracts(type_name: str, contracts: list[dict]) -> list[dict]:
    """Infer likely fields for a value object from contract method params/returns.

    Looks for methods that return this type and examines their params as hints.
    """
    hints: list[dict] = []
    base = type_name.removesuffix("Model") if type_name.endswith("Model") else type_name

    for contract in contracts:
        methods = contract.get("methods", {})
        if isinstance(methods, dict):
            method_list = [{"name": k, **(v if isinstance(v, dict) else {})} for k, v in methods.items()]
        elif isinstance(methods, list):
            method_list = methods
        else:
            continue

        for method in method_list:
            # Check if this method returns our type
            returns = method.get("returns", {})
            ret_type = returns.get("type", "") if isinstance(returns, dict) else str(returns)
            if base not in ret_type:
                continue

            # Method params hint at fields of the returned type
            params = method.get("params", {})
            if isinstance(params, dict):
                for pname, pdef in params.items():
                    ptype = pdef.get("type", "str") if isinstance(pdef, dict) else str(pdef)
                    hints.append({"name": pname, "type": ptype})
            elif isinstance(params, list):
                for p in params:
                    if isinstance(p, dict):
                        hints.append({"name": p.get("name", "field"), "type": p.get("type", "str")})

    return hints


def _generate_stub(class_name: str, fields: list[dict] | None = None) -> str:
    """Generate a Pydantic BaseModel stub for the given class name.

    When *fields* is provided, generates typed field declarations.
    Otherwise generates a stub with an YDK-TODO comment.
    """
    # Ensure class name has Model suffix for consistency
    if not class_name.endswith("Model"):
        model_name = f"{class_name}Model"
    else:
        model_name = class_name

    if fields:
        # Generate actual field declarations
        imports: set[str] = {"from pydantic import BaseModel"}
        field_lines: list[str] = []
        for f in fields:
            fname = f.get("name", "field")
            ftype = f.get("type", "str")
            # Map common YDK types to Python types
            type_map = {
                "string": "str",
                "integer": "int",
                "number": "float",
                "boolean": "bool",
                "decimal": "Decimal",
                "date": "date",
                "datetime": "datetime",
                "uuid": "UUID",
            }
            # Handle union types with pipe (e.g. "Decimal | null", "str|null")
            if "|" in ftype:
                parts = []
                for part in ftype.split("|"):
                    part = part.strip()
                    if part.lower() in ("null", "none"):
                        parts.append("None")
                    else:
                        mapped_part = type_map.get(part.lower(), part)
                        parts.append(mapped_part)
                py_type = " | ".join(parts)
            else:
                py_type = type_map.get(ftype.lower(), ftype)
                # Convert standalone "null" to "None"
                if py_type.lower() == "null":
                    py_type = "None"
            if "Decimal" in py_type:
                imports.add("from decimal import Decimal")
            if "date" in py_type and "datetime" not in py_type:
                imports.add("from datetime import date")
            if "datetime" in py_type:
                imports.add("from datetime import datetime")
            if "UUID" in py_type:
                imports.add("from uuid import UUID")
            field_lines.append(f"    {fname}: {py_type}")

        imports_str = "\n".join(sorted(imports))
        fields_str = "\n".join(field_lines)
        return f'''"""Value object for {model_name}."""

{imports_str}


class {model_name}(BaseModel):
    """Value object — fields derived from entity/contract definitions."""

{fields_str}
'''

    return f'''"""Value object stub for {model_name}."""

from pydantic import BaseModel


class {model_name}(BaseModel):
    """Value object stub — implement fields during Stage 03."""

    pass  # YDK-TODO: define fields for {model_name}
'''


def main() -> None:
    contract_path = os.environ.get("YDK_COMPONENTS_CONTRACT", "")
    entity_path = os.environ.get("YDK_COMPONENTS_ENTITY", "")

    # Load contracts
    contracts: list[dict] = []
    if contract_path and Path(contract_path).exists():
        data = yaml.safe_load(Path(contract_path).read_text(encoding="utf-8"))
        if isinstance(data, list):
            contracts = data

    # Load entities
    entities: list[dict] = []
    if entity_path and Path(entity_path).exists():
        data = yaml.safe_load(Path(entity_path).read_text(encoding="utf-8"))
        if isinstance(data, list):
            entities = data

    if not contracts:
        print("[]")
        return

    # Scan contracts for type references
    referenced_types = _scan_contracts(contracts)

    # Get entity names (already have generators)
    entity_names = _collect_entity_names(entities)

    # Filter: only types NOT covered by entities
    missing_types = set()
    for ref in referenced_types:
        # Check both raw name and Model-suffixed form against entities
        if ref not in entity_names and f"{ref}Model" not in entity_names:
            # Also check if stripping Model suffix matches an entity
            base = ref.removesuffix("Model") if ref.endswith("Model") else ref
            if base not in entity_names and f"{base}Model" not in entity_names:
                missing_types.add(ref)

    # Build field map from entities for field derivation
    entity_field_map = _collect_entity_fields(entities)

    # Generate stubs
    output = []
    for type_name in sorted(missing_types):
        # Try to derive fields: first from entities, then from contracts
        base = type_name.removesuffix("Model") if type_name.endswith("Model") else type_name
        fields = entity_field_map.get(base) or entity_field_map.get(type_name)
        if not fields:
            fields = _infer_fields_from_contracts(type_name, contracts) or None
        content = _generate_stub(type_name, fields=fields)
        # Derive file path: snake_case of the base name (without Model suffix)
        base_name = type_name.removesuffix("Model") if type_name.endswith("Model") else type_name
        snake = to_snake(base_name)
        output.append({"path": f"app/core/models/{snake}.py", "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()

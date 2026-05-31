"""Component registry — loads schemas, resolves IDs, validates manifests."""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Any

import yaml

from odk.models.component import ComponentId, ComponentManifest, SchemaDefinition, SchemaField

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("odk.component_registry")


class ComponentRegistryError(Exception):
    """Raised for registry-level errors (missing schema, invalid manifest, etc.)."""


class ComponentRegistry:
    """Central registry for component schemas and manifests.

    Loads schemas from YAML, resolves component IDs to file paths,
    validates manifests against schemas, and manages component lifecycle.
    """

    def __init__(self, schemas_dir: Path, components_dir: Path) -> None:
        self._schemas_dir = schemas_dir
        self._components_dir = components_dir
        self._schemas: dict[str, SchemaDefinition] | None = None

    def load_schemas(self) -> dict[str, SchemaDefinition]:
        """Read all .yaml files in schemas_dir and return parsed SchemaDefinitions."""
        if self._schemas is not None:
            return self._schemas

        schemas: dict[str, SchemaDefinition] = {}
        if not self._schemas_dir.is_dir():
            self._schemas = schemas
            return schemas

        for yaml_file in sorted(self._schemas_dir.glob("*.yaml")):
            data = yaml.safe_load(yaml_file.read_text())
            if not data or not isinstance(data, dict):
                continue
            fields: dict[str, SchemaField] = {}
            for field_name, field_data in data.get("fields", {}).items():
                if isinstance(field_data, dict):
                    fields[field_name] = SchemaField(
                        type=field_data.get("type", "any"),
                        required=field_data.get("required", False),
                        description=field_data.get("description", ""),
                        pattern=field_data.get("pattern"),
                        values=field_data.get("values"),
                        ref_type=field_data.get("ref_type"),
                        default=field_data.get("default"),
                        items=field_data.get("items"),
                        max_length=field_data.get("max_length"),
                        min=field_data.get("min"),
                        max=field_data.get("max"),
                    )
            schema = SchemaDefinition(
                name=data["name"],
                description=data.get("description", ""),
                version=data.get("version", 1),
                fields=fields,
            )
            schemas[schema.name] = schema

        self._schemas = schemas
        return schemas

    def resolve_id(self, component_id: str) -> Path:
        """Convert odk:type:namespace/name to a file path under components_dir."""
        parsed = ComponentId.parse(component_id)
        if parsed.namespace:
            return self._components_dir / parsed.type / parsed.namespace / f"{parsed.name}.yaml"
        return self._components_dir / parsed.type / f"{parsed.name}.yaml"

    def load_component(self, component_id: str) -> ComponentManifest:
        """Read and parse a component YAML file by its ID."""
        path = self.resolve_id(component_id)
        if not path.exists():
            msg = f"Component file not found: {path} (id: {component_id})"
            raise ComponentRegistryError(msg)

        data = yaml.safe_load(path.read_text())
        if not data or not isinstance(data, dict):
            msg = f"Empty or invalid YAML in {path}"
            raise ComponentRegistryError(msg)

        schema_ref = data.pop("$schema", None)
        if not schema_ref:
            msg = f"Missing $schema in {path}"
            raise ComponentRegistryError(msg)

        return ComponentManifest(schema_ref=schema_ref, **data)

    def validate_component(self, component_id: str) -> list[str]:
        """Validate a component against its schema. Returns list of errors."""
        start = time.monotonic()
        errors: list[str] = []
        path = self.resolve_id(component_id)

        if not path.exists():
            return [f"Component file not found: {path}"]

        data = yaml.safe_load(path.read_text())
        if not data or not isinstance(data, dict):
            return [f"Empty or invalid YAML in {path}"]

        schema_ref = data.get("$schema")
        if not schema_ref:
            return [f"Missing $schema in {path}"]
        if not schema_ref.startswith("odk:schema:"):
            return [f"Invalid $schema format: {schema_ref}"]

        schema_type = schema_ref.removeprefix("odk:schema:")
        schemas = self.load_schemas()
        if schema_type not in schemas:
            return [f"Unknown schema type: {schema_type}"]

        component_id_value = data.get("id")
        if not component_id_value:
            errors.append(f"Missing id in {path}")
        elif component_id_value != component_id:
            errors.append(f"ID mismatch: file expects {component_id}, manifest declares {component_id_value}")

        schema = schemas[schema_type]
        errors.extend(self._validate_fields(data, schema, str(path)))
        elapsed = time.monotonic() - start
        logger.debug(
            "Validated %s in %.3fs — %d error(s)",
            component_id,
            elapsed,
            len(errors),
        )
        return errors

    def _validate_fields(self, data: dict[str, Any], schema: SchemaDefinition, path: str) -> list[str]:
        """Validate manifest fields against schema definition."""
        errors: list[str] = []
        for field_name, field_def in schema.fields.items():
            if field_name in ("id",):
                continue
            if field_def.required and field_name not in data:
                errors.append(f"Missing required field '{field_name}' in {path}")
                continue
            if field_name not in data:
                continue
            value = data[field_name]
            errors.extend(self._validate_field_value(field_name, value, field_def, path))
        return errors

    def _validate_field_value(self, field_name: str, value: object, field_def: SchemaField, path: str) -> list[str]:
        """Validate a single field value against its schema definition."""
        errors: list[str] = []
        if field_def.type == "enum" and field_def.values:
            if value not in field_def.values:
                errors.append(f"Field '{field_name}': expected one of {field_def.values}, got '{value}' in {path}")
        elif field_def.type == "string" and field_def.pattern:
            if isinstance(value, str) and not re.match(field_def.pattern, value):
                errors.append(f"Field '{field_name}': does not match pattern '{field_def.pattern}' in {path}")
        elif field_def.type == "integer":
            if not isinstance(value, int):
                errors.append(f"Field '{field_name}': expected integer, got {type(value).__name__} in {path}")
        elif field_def.type == "boolean":
            if not isinstance(value, bool):
                errors.append(f"Field '{field_name}': expected boolean, got {type(value).__name__} in {path}")
        elif field_def.type in ("list", "ref_list"):
            if not isinstance(value, list):
                errors.append(f"Field '{field_name}': expected list, got {type(value).__name__} in {path}")
        elif field_def.type == "map" and not isinstance(value, dict):
            errors.append(f"Field '{field_name}': expected map, got {type(value).__name__} in {path}")
        return errors

    def validate_all(self) -> dict[str, list[str]]:
        """Validate every component file. Returns dict of component_id -> errors."""
        results: dict[str, list[str]] = {}
        if not self._components_dir.is_dir():
            return results

        for yaml_file in self._components_dir.rglob("*.yaml"):
            data = yaml.safe_load(yaml_file.read_text())
            if not data or not isinstance(data, dict):
                continue
            component_id = data.get("id")
            if not component_id:
                rel = yaml_file.relative_to(self._components_dir)
                results[str(rel)] = [f"Missing id in {yaml_file}"]
                continue
            errors = self.validate_component(component_id)
            if errors:
                results[component_id] = errors
        return results

    def list_components(self, type_filter: str | None = None) -> list[ComponentId]:
        """List all components, optionally filtered by type."""
        components: list[ComponentId] = []
        if not self._components_dir.is_dir():
            return components

        for yaml_file in sorted(self._components_dir.rglob("*.yaml")):
            data = yaml.safe_load(yaml_file.read_text())
            if not data or not isinstance(data, dict):
                continue
            component_id = data.get("id")
            if not component_id:
                continue
            try:
                parsed = ComponentId.parse(component_id)
            except ValueError:
                continue
            if type_filter and parsed.type != type_filter:
                continue
            components.append(parsed)
        return components

    def list_schemas(self) -> list[SchemaDefinition]:
        """List all available schema definitions."""
        schemas = self.load_schemas()
        return sorted(schemas.values(), key=lambda s: s.name)

    def create_component(self, type_name: str, namespace_name: str) -> Path:
        """Create a new component from a schema template."""
        schemas = self.load_schemas()
        if type_name not in schemas:
            msg = f"Unknown schema type: {type_name}"
            raise ComponentRegistryError(msg)

        component_id = f"odk:{type_name}:{namespace_name}"
        path = self.resolve_id(component_id)

        if path.exists():
            msg = f"Component already exists: {path}"
            raise ComponentRegistryError(msg)

        path.parent.mkdir(parents=True, exist_ok=True)

        schema = schemas[type_name]
        manifest: dict[str, object] = {
            "$schema": f"odk:schema:{type_name}",
            "id": component_id,
        }
        for field_name, field_def in schema.fields.items():
            if field_name == "id":
                continue
            if field_def.default is not None:
                manifest[field_name] = field_def.default
            elif field_def.type in ("string", "text"):
                manifest[field_name] = ""
            elif field_def.type == "integer":
                manifest[field_name] = 0
            elif field_def.type == "boolean":
                manifest[field_name] = False
            elif field_def.type == "enum" and field_def.values:
                manifest[field_name] = field_def.values[0]
            elif field_def.type in ("list", "ref_list"):
                manifest[field_name] = []
            elif field_def.type == "map":
                manifest[field_name] = {}
            elif field_def.type == "ref":
                manifest[field_name] = ""
            elif field_def.type == "any":
                manifest[field_name] = None

        path.write_text(yaml.dump(manifest, default_flow_style=False, sort_keys=False))
        return path

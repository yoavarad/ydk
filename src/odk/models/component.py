"""Pydantic models for the component manifest system."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, field_validator

_ID_RE = r"^odk:[a-z][a-z0-9_-]*:[a-zA-Z0-9_-]+(/[a-zA-Z0-9_.-]+)+$"
_ID_RE_NO_SLASH = r"^odk:[a-z][a-z0-9_-]*:[a-zA-Z0-9_.-]+$"
_ID_PATTERN = re.compile(f"{_ID_RE}|{_ID_RE_NO_SLASH}")


class ComponentId(BaseModel):
    """Parsed component ID with type, namespace, and name."""

    model_config = ConfigDict(extra="forbid")

    full_id: str
    type: str
    namespace: str
    name: str

    @field_validator("full_id")
    @classmethod
    def validate_id_format(cls, v: str) -> str:
        """Ensure ID matches odk:<type>:<namespace>/<name> pattern."""
        if not v.startswith("odk:"):
            msg = f"Component ID must start with 'odk:': {v}"
            raise ValueError(msg)
        parts = v.split(":", 2)
        if len(parts) != 3 or not parts[1] or not parts[2]:
            msg = f"Invalid component ID format: {v}"
            raise ValueError(msg)
        if not _ID_PATTERN.match(v):
            msg = f"Invalid component ID format: {v}"
            raise ValueError(msg)
        return v

    @classmethod
    def parse(cls, full_id: str) -> ComponentId:
        """Parse a full component ID string into its parts."""
        if not full_id.startswith("odk:"):
            msg = f"Component ID must start with 'odk:': {full_id}"
            raise ValueError(msg)
        parts = full_id.split(":", 2)
        if len(parts) != 3 or not parts[1] or not parts[2]:
            msg = f"Invalid component ID format: {full_id}"
            raise ValueError(msg)
        type_name = parts[1]
        namespace_name = parts[2]
        if "/" in namespace_name:
            last_slash = namespace_name.rfind("/")
            namespace = namespace_name[:last_slash]
            name = namespace_name[last_slash + 1 :]
        else:
            namespace = ""
            name = namespace_name
        return cls(full_id=full_id, type=type_name, namespace=namespace, name=name)


class SchemaField(BaseModel):
    """Field definition within a component schema."""

    model_config = ConfigDict(extra="forbid")

    type: str
    required: bool = False
    description: str
    pattern: str | None = None
    values: list[str] | None = None
    ref_type: str | None = None
    default: object | None = None
    items: dict[str, object] | None = None
    max_length: int | None = None
    min: int | None = None
    max: int | None = None


class SchemaDefinition(BaseModel):
    """A component type schema loaded from YAML."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    version: int
    fields: dict[str, SchemaField]


class ComponentManifest(BaseModel):
    """A component manifest loaded from YAML, validated against its schema."""

    model_config = ConfigDict(extra="allow")

    schema_ref: str
    id: str

    @field_validator("schema_ref")
    @classmethod
    def validate_schema_ref(cls, v: str) -> str:
        """Ensure $schema follows odk:schema:<type> format."""
        if not v.startswith("odk:schema:"):
            msg = f"$schema must start with 'odk:schema:': {v}"
            raise ValueError(msg)
        return v

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Ensure id follows odk:<type>:<namespace>/<name> format."""
        if not v.startswith("odk:"):
            msg = f"Component ID must start with 'odk:': {v}"
            raise ValueError(msg)
        return v


class LinkerResult(BaseModel):
    """Results of Layer A validation (deterministic linker)."""

    model_config = ConfigDict(extra="forbid")

    undefined_refs: list[str]
    orphaned_components: list[str]
    broken_cross_refs: list[str]
    valid_refs: list[str]


class ScannerFinding(BaseModel):
    """A single finding from the LLM prose scanner."""

    model_config = ConfigDict(extra="forbid")

    text: str
    line: int
    suggested_id: str
    confidence: str
    reason: str


class ScannerResult(BaseModel):
    """Results of Layer B scanning (LLM prose scanner)."""

    model_config = ConfigDict(extra="forbid")

    unlinked_mentions: list[ScannerFinding]
    suggested_ids: list[str]


class ValidationResult(BaseModel):
    """Combined schema + linker + scanner validation results."""

    model_config = ConfigDict(extra="forbid")

    schema_errors: dict[str, list[str]]
    linker_result: LinkerResult
    scanner_result: ScannerResult | None = None

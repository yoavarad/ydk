"""Catalog data models — items, manifests, references, and publish checks."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 — Pydantic needs Path at runtime

from pydantic import BaseModel, ConfigDict


class InputSpec(BaseModel):
    """Describes an expected input schema for an ignition pack."""

    model_config = ConfigDict(extra="forbid")

    schema_ref: str  # e.g., "odk-core-schemas/entity"
    version: str  # e.g., ">=1.0.0"
    required: bool = True


class Reference(BaseModel):
    """A semver-constrained dependency reference."""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str  # semver constraint, e.g. ">=1.0.0"


class PublishCheck(BaseModel):
    """A pre-publish validation check."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    command: str = ""  # optional shell command to run


class CatalogItem(BaseModel):
    """A resolved catalog entry with its local path."""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    tags: list[str] = []
    path: Path  # local path to the item directory


class CatalogManifest(BaseModel):
    """The catalog.yaml manifest declaring an item's metadata and dependencies."""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    description: str = ""
    tags: list[str] = []
    inputs: dict[str, InputSpec] = {}  # for ignition packs
    verification_sets: list[Reference] = []
    spec_reviewers: list[Reference] = []
    component_schemas: list[Reference] = []
    publish_checks: list[PublishCheck] = []

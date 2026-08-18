"""Trigger event model for the named trigger system."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

_TRIGGER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*:[a-z][a-z0-9-]*$")


def validate_trigger_id(trigger_id: str) -> str:
    """Validate a trigger ID matches the namespace:name format."""
    if not _TRIGGER_ID_PATTERN.match(trigger_id):
        msg = f"Invalid trigger ID {trigger_id!r}. Must match <namespace>:<name> (lowercase alphanumeric + hyphens)."
        raise ValueError(msg)
    return trigger_id


class TriggerEvent(BaseModel):
    """An event emitted when a trigger fires."""

    model_config = ConfigDict(extra="forbid")

    id: str
    trigger_id: str
    timestamp: str
    context: dict[str, Any]

    @field_validator("trigger_id")
    @classmethod
    def _validate_trigger_id(cls, v: str) -> str:
        return validate_trigger_id(v)

    @classmethod
    def create(cls, trigger_id: str, context: dict[str, Any] | None = None) -> TriggerEvent:
        """Factory: create a new event with auto-generated ID and timestamp."""
        return cls(
            id=uuid.uuid4().hex[:12],
            trigger_id=trigger_id,
            timestamp=datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            context=context or {},
        )

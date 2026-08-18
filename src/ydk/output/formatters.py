"""Strategy pattern for output formats."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Protocol

import yaml
from pydantic import BaseModel

# Union covering all data types the formatters accept.
FormattableData = BaseModel | dict[str, object] | list[object] | str


class OutputFormat(StrEnum):
    """Available output format identifiers."""

    human = "human"
    json = "json"
    yaml = "yaml"


class Formatter(Protocol):
    """Protocol for output format strategies."""

    def format(self, data: FormattableData) -> str:
        """Serialize *data* into a string representation."""
        ...


class HumanFormatter:
    """Rich-based human-readable output."""

    def format(self, data: FormattableData) -> str:
        """Render data as human-friendly text with Rich markup."""
        if isinstance(data, str):
            return data
        if isinstance(data, BaseModel):
            data = data.model_dump()
        if isinstance(data, dict):
            lines: list[str] = []
            for key, value in data.items():
                lines.append(f"[bold]{key}[/bold]: {value}")
            return "\n".join(lines)
        return str(data)


class JsonFormatter:
    """JSON output with indent=2."""

    def format(self, data: FormattableData) -> str:
        """Render data as pretty-printed JSON."""
        if isinstance(data, BaseModel):
            data = data.model_dump()
        return json.dumps(data, indent=2, default=str)


class YamlFormatter:
    """YAML output."""

    def format(self, data: FormattableData) -> str:
        """Render data as YAML."""
        if isinstance(data, BaseModel):
            data = data.model_dump()
        return yaml.dump(data, default_flow_style=False, sort_keys=False)


_FORMATTERS: dict[OutputFormat, type[HumanFormatter | JsonFormatter | YamlFormatter]] = {
    OutputFormat.human: HumanFormatter,
    OutputFormat.json: JsonFormatter,
    OutputFormat.yaml: YamlFormatter,
}


def get_formatter(fmt: OutputFormat) -> HumanFormatter | JsonFormatter | YamlFormatter:
    """Factory function."""
    cls = _FORMATTERS.get(fmt)
    if cls is None:
        msg = f"Unknown format: {fmt}"
        raise ValueError(msg)
    return cls()

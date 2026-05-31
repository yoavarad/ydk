"""Naming utilities for the python-typer-cli generators."""

from __future__ import annotations

import re


def to_snake(name: str) -> str:
    """Convert a kebab-case or camelCase name to snake_case."""
    # Replace hyphens with underscores
    s = name.replace("-", "_")
    # Insert underscore before uppercase letters (camelCase)
    s = re.sub(r"([A-Z])", r"_\1", s).lower()
    # Clean up double underscores
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def to_kebab(name: str) -> str:
    """Convert snake_case to kebab-case."""
    return name.replace("_", "-")


def to_class_name(name: str) -> str:
    """Convert a snake/kebab name to PascalCase."""
    parts = name.replace("-", "_").split("_")
    return "".join(p.capitalize() for p in parts)

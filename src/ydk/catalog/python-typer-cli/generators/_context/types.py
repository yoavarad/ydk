"""Type mapping utilities for the python-typer-cli generators."""

from __future__ import annotations

# Maps artifact type strings to Python type annotations
ARTIFACT_TO_PYTHON: dict[str, str] = {
    "str": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "list[str]": "list[str]",
}


def python_type(artifact_type: str) -> str:
    """Return the Python type annotation for an artifact type string."""
    return ARTIFACT_TO_PYTHON.get(artifact_type, "str")


def typer_default(default_value: object, type_str: str) -> str:
    """Return a string representation of a Typer default value."""
    if default_value is None:
        return "None"
    if type_str == "str":
        return f'"{default_value}"'
    if type_str == "bool":
        return str(default_value)
    return str(default_value)

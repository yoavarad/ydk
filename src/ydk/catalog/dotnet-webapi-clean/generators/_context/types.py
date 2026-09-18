"""Canonical type mappings for YDK dotnet-webapi-clean generators (YDK canonical type system)."""

from __future__ import annotations

# YDK canonical type string -> C# type name
CANONICAL_TO_CSHARP: dict[str, str] = {
    "string": "string",
    "integer": "int",
    "bigint": "long",
    "float": "double",
    "boolean": "bool",
    "uuid": "Guid",
    "decimal": "decimal",
    "datetime": "DateTime",
    "date": "DateOnly",
    "text": "string",
    "json": "string",
    "enum": "string",
    "bytes": "byte[]",
    # Legacy aliases (for backward compatibility)
    "str": "string",
    "int": "int",
    "bool": "bool",
    "UUID": "Guid",
    "Decimal": "decimal",
    # Optional wrappers -> nullable C# type
    "optional[string]": "string?",
    "optional[integer]": "int?",
    "optional[int]": "int?",
    "optional[bigint]": "long?",
    "optional[float]": "double?",
    "optional[boolean]": "bool?",
    "optional[bool]": "bool?",
    "optional[uuid]": "Guid?",
    "optional[UUID]": "Guid?",
    "optional[decimal]": "decimal?",
    "optional[Decimal]": "decimal?",
    "optional[datetime]": "DateTime?",
    "optional[date]": "DateOnly?",
    "optional[text]": "string?",
    "optional[json]": "string?",
    "optional[str]": "string?",
    "optional[bytes]": "byte[]?",
    # Collection types
    "list[str]": "List<string>",
    "list[string]": "List<string>",
    "list[int]": "List<int>",
    "list[integer]": "List<int>",
    "optional[list[str]]": "List<string>?",
    "optional[list[string]]": "List<string>?",
    "any": "object",
}

# YDK canonical type -> EF Core column type hint (used with `.HasColumnType(...)`).
# Only listed where SQLite's default EF Core mapping needs an explicit nudge;
# omitted/None entries rely on EF Core's default SQLite type mapping.
CANONICAL_TO_EFCORE_COLUMN: dict[str, str | None] = {
    "decimal": "TEXT",
    "Decimal": "TEXT",
    "optional[decimal]": "TEXT",
    "optional[Decimal]": "TEXT",
    "datetime": "TEXT",
    "optional[datetime]": "TEXT",
    "date": "TEXT",
    "optional[date]": "TEXT",
    "uuid": "TEXT",
    "UUID": "TEXT",
    "optional[uuid]": "TEXT",
    "optional[UUID]": "TEXT",
    "bytes": "BLOB",
    "optional[bytes]": "BLOB",
}

# Canonical types that map to a nullable C# type.
NULLABLE_TYPES: frozenset[str] = frozenset(t for t in CANONICAL_TO_CSHARP if t.startswith("optional["))

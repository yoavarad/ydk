#!/usr/bin/env python3
"""Generator: resolve-commands (YDK ignition pack).

Resolve cli-intent + openapi.json into full cli-commands.yaml.

When both cli-intent and openapi.json are present in YDK components,
this generator resolves each command's operation_id against the OpenAPI
spec to produce a complete cli-commands structure that downstream
generators consume.

If openapi data is absent, this generator emits an empty list — the user
is expected to provide cli-commands directly via the contract component.

YDK protocol: reads YDK_COMPONENTS_* env vars, prints JSON array to stdout.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

# Map OpenAPI types to CLI artifact types
_OPENAPI_TO_CLI_TYPE: dict[str, str] = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list[str]",
}


def _find_operation(spec: dict, operation_id: str) -> tuple[str, str, dict] | None:
    """Find an operation in the OpenAPI spec by operationId."""
    for path, methods in spec.get("paths", {}).items():
        for method, operation in methods.items():
            if isinstance(operation, dict) and operation.get("operationId") == operation_id:
                return method.upper(), path, operation
    return None


def _resolve_schema(spec: dict, schema: dict) -> dict:
    """Resolve a $ref schema to its actual definition."""
    if "$ref" in schema:
        ref_path = schema["$ref"].lstrip("#/").split("/")
        resolved = spec
        for part in ref_path:
            resolved = resolved.get(part, {})
        return resolved
    return schema


def _extract_arguments(parameters: list[dict]) -> list[dict]:
    """Extract path parameters as CLI arguments."""
    arguments = []
    for param in parameters:
        if param.get("in") == "path":
            schema = param.get("schema", {})
            arguments.append(
                {
                    "name": param["name"],
                    "type": _OPENAPI_TO_CLI_TYPE.get(schema.get("type", "string"), "str"),
                    "description": param.get("description", f"{param['name']} parameter"),
                }
            )
    return arguments


def _extract_options(spec: dict, operation: dict) -> list[dict]:
    """Extract query parameters and request body fields as CLI options."""
    options = []

    # Query parameters
    for param in operation.get("parameters", []):
        if param.get("in") == "query":
            schema = param.get("schema", {})
            opt: dict[str, object] = {
                "name": param["name"],
                "type": _OPENAPI_TO_CLI_TYPE.get(schema.get("type", "string"), "str"),
                "description": param.get("description", f"{param['name']} option"),
            }
            if param.get("required"):
                opt["required"] = True
            if "default" in schema:
                opt["default"] = schema["default"]
            else:
                opt["default"] = None
            options.append(opt)

    # Request body fields
    request_body = operation.get("requestBody", {})
    content = request_body.get("content", {})
    json_content = content.get("application/json", {})
    body_schema = json_content.get("schema", {})

    if body_schema:
        resolved = _resolve_schema(spec, body_schema)
        required_fields = resolved.get("required", [])
        properties = resolved.get("properties", {})

        for field_name, field_schema in properties.items():
            opt = {
                "name": field_name,
                "type": _OPENAPI_TO_CLI_TYPE.get(field_schema.get("type", "string"), "str"),
                "description": field_schema.get("description", f"{field_name} field"),
            }
            if field_name in required_fields:
                opt["required"] = True
            if "default" in field_schema:
                opt["default"] = field_schema["default"]
            options.append(opt)

    return options


def _infer_response_type(operation: dict) -> str:
    """Infer response type from the operation's success response."""
    responses = operation.get("responses", {})
    for code in ("200", "201", "202"):
        response = responses.get(code, {})
        content = response.get("content", {})
        json_content = content.get("application/json", {})
        schema = json_content.get("schema", {})
        if schema.get("type") == "array":
            return "list"
        if schema.get("type") == "object" or "$ref" in schema:
            return "object"
    if "204" in responses:
        return "empty"
    return "object"


def main() -> None:
    """Resolve intent + openapi into cli-commands, or skip if unavailable."""
    # In YDK, openapi and intent data come through components
    openapi_path = os.environ.get("YDK_COMPONENTS_OPENAPI", "")
    intent_path = os.environ.get("YDK_COMPONENTS_INTENT", "")

    if not openapi_path or not Path(openapi_path).exists():
        print(
            "Info: openapi component not available — resolve-commands skipped.",
            file=sys.stderr,
        )
        print(json.dumps([]))
        return

    if not intent_path or not Path(intent_path).exists():
        print(
            "Info: intent component not available — resolve-commands skipped.",
            file=sys.stderr,
        )
        print(json.dumps([]))
        return

    spec_raw = yaml.safe_load(Path(openapi_path).read_text(encoding="utf-8"))
    intent_raw = yaml.safe_load(Path(intent_path).read_text(encoding="utf-8"))

    # Components arrive as lists; take the first item
    spec = spec_raw[0] if isinstance(spec_raw, list) else spec_raw
    intent = intent_raw[0] if isinstance(intent_raw, list) else intent_raw

    # If spec is stored as JSON string inside YAML, parse it
    if isinstance(spec, str):
        spec = json.loads(spec)

    commands_data: dict[str, object] = {
        "app_name": intent.get("app_name", "cli"),
        "base_url_env": intent.get("base_url_env", "CLI_BASE_URL"),
    }

    if "auth" in intent:
        commands_data["auth"] = intent["auth"]

    groups: list[dict] = []
    for group in intent.get("groups", []):
        resolved_group: dict[str, object] = {
            "name": group["name"],
            "description": group.get("description", ""),
        }

        resolved_commands: list[dict] = []
        for cmd in group.get("commands", []):
            operation_id = cmd.get("operation_id")
            if not operation_id:
                continue

            result = _find_operation(spec, operation_id)
            if not result:
                print(
                    f"Warning: operation_id '{operation_id}' not found in OpenAPI spec — skipping.",
                    file=sys.stderr,
                )
                continue

            method, path, operation = result

            resolved_cmd: dict[str, object] = {
                "name": cmd["name"],
                "description": cmd.get("description", operation.get("summary", "")),
                "method": method,
                "endpoint": path,
            }

            arguments = _extract_arguments(operation.get("parameters", []))
            if arguments:
                resolved_cmd["arguments"] = arguments

            options = _extract_options(spec, operation)
            if options:
                resolved_cmd["options"] = options

            resolved_cmd["response_type"] = _infer_response_type(operation)
            resolved_commands.append(resolved_cmd)

        resolved_group["commands"] = resolved_commands
        groups.append(resolved_group)

    commands_data["groups"] = groups

    content = yaml.dump(commands_data, default_flow_style=False, sort_keys=False)
    print(json.dumps([{"path": ".ydk/resolved/cli-commands.yaml", "content": content}]))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Generator: derive-features
Derive frontend-features.yaml from openapi.json + page components.

When openapi.json is present, this generator inspects page mutations,
looks up each operation in the OpenAPI spec, and produces a frontend-features.yaml
with form metadata and validation derived from the spec.

If openapi.json is absent, this generator exits 0 with no output —
the user is expected to hand-author frontend-features.yaml instead.

If frontend-features.yaml already exists (hand-edited), this generator writes
to frontend-features.derived.yaml and emits a warning.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml


def _find_operation(spec: dict, operation_id: str) -> dict | None:
    """Find an operation in the OpenAPI spec by operationId."""
    for _path, methods in spec.get("paths", {}).items():
        for _method, operation in methods.items():
            if isinstance(operation, dict) and operation.get("operationId") == operation_id:
                return operation
    return None


def _has_request_body(operation: dict) -> bool:
    """Check if an operation has a request body."""
    return bool(operation.get("requestBody"))


def _extract_validation(spec: dict, operation: dict) -> list[dict]:
    """Extract validation rules from request body schema."""
    validations: list[dict] = []
    request_body = operation.get("requestBody", {})
    content = request_body.get("content", {})
    json_content = content.get("application/json", {})
    schema = json_content.get("schema", {})

    # Resolve $ref if present
    if "$ref" in schema:
        ref_path = schema["$ref"].lstrip("#/").split("/")
        resolved = spec
        for part in ref_path:
            resolved = resolved.get(part, {})
        schema = resolved

    required_fields = schema.get("required", [])
    properties = schema.get("properties", {})

    for field_name, field_schema in properties.items():
        rules: dict[str, object] = {"field": field_name}
        if field_name in required_fields:
            rules["required"] = True
        if "minLength" in field_schema:
            rules["min_length"] = field_schema["minLength"]
        if "maxLength" in field_schema:
            rules["max_length"] = field_schema["maxLength"]
        if "enum" in field_schema:
            rules["enum"] = field_schema["enum"]
        if len(rules) > 1:  # more than just 'field'
            validations.append(rules)

    return validations


def main() -> None:
    # Check for OpenAPI spec
    openapi_path = os.environ.get("ODK_ARTIFACT_OPENAPI", "")
    if not openapi_path or not Path(openapi_path).exists():
        print(
            "Warning: ODK_ARTIFACT_OPENAPI not available — derive-features skipped. "
            "Hand-author frontend-features.yaml instead.",
            file=sys.stderr,
        )
        print(json.dumps([]))
        return

    # Check for page components
    pages_path = os.environ.get("ODK_COMPONENTS_PAGE", "")
    if not pages_path or not Path(pages_path).exists():
        print(
            "Warning: ODK_COMPONENTS_PAGE not available — derive-features skipped.",
            file=sys.stderr,
        )
        print(json.dumps([]))
        return

    spec = json.loads(Path(openapi_path).read_text(encoding="utf-8"))

    # ODK passes a plain YAML list of page components
    pages = yaml.safe_load(Path(pages_path).read_text(encoding="utf-8")) or []
    if isinstance(pages, dict):
        pages = pages.get("pages", [])

    # Collect all mutations referenced across all pages (including children)
    def collect_mutations(page_list: list[dict]) -> dict[str, list[str]]:
        """Map mutation operation_id -> list of query operation_ids on same page."""
        result: dict[str, list[str]] = {}
        for page in page_list:
            mutations = page.get("mutations", [])
            queries = page.get("queries", [])
            for mutation in mutations:
                if isinstance(mutation, str):
                    if mutation not in result:
                        result[mutation] = []
                    result[mutation].extend(q for q in queries if q not in result[mutation])
            # Recurse into children
            children = page.get("children", [])
            if children:
                child_result = collect_mutations(children)
                for k, v in child_result.items():
                    if k not in result:
                        result[k] = []
                    result[k].extend(q for q in v if q not in result[k])
        return result

    mutation_map = collect_mutations(pages)

    if not mutation_map:
        print(json.dumps([]))
        return

    # Generate features from mutations
    features: list[dict] = []
    for mutation_id, related_queries in mutation_map.items():
        operation = _find_operation(spec, mutation_id)
        if not operation:
            continue

        feature: dict[str, object] = {
            "id": mutation_id.replace("Api", "-")
            .replace("ById", "")
            .lower()
            .replace("post", "create-")
            .replace("put", "update-")
            .replace("delete", "delete-")
            .replace("patch", "patch-")
            .rstrip("-"),
            "title": operation.get("summary", mutation_id),
            "queries": related_queries,
            "mutations": [mutation_id],
            "events": [],
            "form": _has_request_body(operation),
        }

        if _has_request_body(operation):
            validation = _extract_validation(spec, operation)
            if validation:
                feature["validation"] = validation

        features.append(feature)

    # Determine output filename
    output_filename = "frontend-features.yaml"
    output_dir = Path(os.environ.get("ODK_OUTPUT_DIR", "."))
    if (output_dir / "frontend-features.yaml").exists():
        output_filename = "frontend-features.derived.yaml"
        print(
            "Warning: frontend-features.yaml already exists. "
            "Writing derived version to frontend-features.derived.yaml. "
            "Diff manually to reconcile.",
            file=sys.stderr,
        )

    content = yaml.dump(
        {"frontend_features": features},
        default_flow_style=False,
        sort_keys=False,
    )

    print(json.dumps([{"path": output_filename, "content": content}]))


if __name__ == "__main__":
    main()

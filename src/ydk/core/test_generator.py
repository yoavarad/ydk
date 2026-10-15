"""Test generator — produces Python test code from component manifests."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment

from ydk.models.test_gen import GeneratedTest


@dataclass
class _FieldConstraint:
    name: str
    constraint_type: str
    constraint_value: Any


@dataclass
class _Transition:
    from_state: str
    to_state: str


@dataclass
class _DefaultField:
    name: str
    default_value: Any
    default_repr: str


@dataclass
class _ErrorResponse:
    status: int
    slug: str
    description: str


@dataclass
class _ShapeField:
    name: str
    type: str


def _slugify(text: str) -> str:
    """Convert text to a safe Python identifier slug."""
    return re.sub(r"[^a-zA-Z0-9]", "_", text).strip("_").lower()


def _class_name_from_id(component_id: str) -> str:
    """Extract a PascalCase class name from a component ID.

    ydk:entity:orders/Order -> Order
    ydk:route:orders/create -> OrdersCreate
    """
    parts = component_id.split(":", 2)
    name_part = parts[2] if len(parts) == 3 else component_id
    segments = re.split(r"[/\-_]", name_part)
    return "".join(seg.capitalize() for seg in segments if seg)


class ComponentTestGenerator:
    """Generates Python test code from component manifests and schemas."""

    def __init__(self) -> None:
        templates_dir = Path(__file__).resolve().parent.parent / "test_templates"
        self._env = Environment(loader=BaseLoader(), keep_trailing_newline=True)
        self._templates_dir = templates_dir

    def _load_template(self, name: str) -> str:
        """Load a Jinja2 template file."""
        path = self._templates_dir / name
        return path.read_text()

    def generate_from_entity(self, manifest: dict[str, Any], schema: dict[str, Any]) -> GeneratedTest:
        """Generate test code for an entity component."""
        component_id = manifest.get("id", "unknown")
        class_name = _class_name_from_id(component_id)
        fields = schema.get("fields", {})

        # Build required fields list
        required_fields = []
        for fname, fdef in fields.items():
            if fname == "id":
                continue
            if isinstance(fdef, dict) and fdef.get("required"):
                required_fields.append({"name": fname})

        # Build valid_data from manifest (all non-meta fields)
        valid_data: dict[str, Any] = {}
        for fname, fdef in fields.items():
            if fname == "id":
                continue
            if isinstance(fdef, dict):
                if fdef.get("default") is not None:
                    valid_data[fname] = fdef["default"]
                elif fdef.get("type") == "string":
                    valid_data[fname] = f"test_{fname}"
                elif fdef.get("type") == "integer":
                    valid_data[fname] = 0
                elif fdef.get("type") == "boolean":
                    valid_data[fname] = False
                elif fdef.get("type") in ("list", "ref_list"):
                    valid_data[fname] = []
                elif fdef.get("type") == "map":
                    valid_data[fname] = {}
                else:
                    valid_data[fname] = ""

        # Build type constraint fields
        type_constrained: list[_FieldConstraint] = []
        for fname, fdef in fields.items():
            if fname == "id" or not isinstance(fdef, dict):
                continue
            if fdef.get("max_length"):
                type_constrained.append(_FieldConstraint(fname, "max_length", fdef["max_length"]))
            if fdef.get("values"):
                type_constrained.append(_FieldConstraint(fname, "enum", fdef["values"]))
            if fdef.get("min") is not None:
                type_constrained.append(_FieldConstraint(fname, "min", fdef["min"]))
            if fdef.get("max") is not None:
                type_constrained.append(_FieldConstraint(fname, "max", fdef["max"]))

        # State transitions
        states = manifest.get("states", [])
        transitions_raw = manifest.get("transitions", [])
        transitions = [
            _Transition(from_state=t["from"], to_state=t["to"])
            for t in transitions_raw
            if isinstance(t, dict) and "from" in t and "to" in t
        ]

        # Nullable fields (not required and not in required list)
        nullable_fields = []
        for fname, fdef in fields.items():
            if fname == "id" or not isinstance(fdef, dict):
                continue
            if not fdef.get("required"):
                nullable_fields.append({"name": fname})

        # Default value fields
        default_fields = []
        for fname, fdef in fields.items():
            if fname == "id" or not isinstance(fdef, dict):
                continue
            if fdef.get("default") is not None:
                default_fields.append(
                    _DefaultField(
                        name=fname,
                        default_value=fdef["default"],
                        default_repr=_slugify(str(fdef["default"])),
                    )
                )

        template_src = self._load_template("entity_tests.py.j2")
        template = self._env.from_string(template_src)
        code = template.render(
            component_id=component_id,
            class_name=class_name,
            required_fields=required_fields,
            valid_data=valid_data,
            type_constrained_fields=type_constrained,
            states=states,
            transitions=transitions,
            nullable_fields=nullable_fields,
            default_fields=default_fields,
        )

        # Count test methods
        test_count = code.count("\n    def test_")

        # Build file path
        parsed_name = component_id.split(":", 2)[-1] if ":" in component_id else component_id
        file_slug = _slugify(parsed_name)
        test_file_path = f"tests/generated/test_{file_slug}.py"

        return GeneratedTest(
            component_id=component_id,
            test_code=code,
            test_file_path=test_file_path,
            test_count=test_count,
        )

    def generate_from_route(self, manifest: dict[str, Any], schema: dict[str, Any]) -> GeneratedTest:
        """Generate test code for a route component."""
        component_id = manifest.get("id", "unknown")
        class_name = _class_name_from_id(component_id)

        method = manifest.get("method", "GET")
        path = manifest.get("path", "/")
        expected_status = manifest.get("status", 200)
        auth_required = manifest.get("auth") == "required"

        # Error responses
        error_responses_raw = manifest.get("errors", [])
        error_responses = [
            _ErrorResponse(
                status=err.get("status", 500),
                slug=_slugify(err.get("description", "error")),
                description=err.get("description", "error"),
            )
            for err in error_responses_raw
            if isinstance(err, dict)
        ]

        # Required request fields from schema
        fields = schema.get("fields", {})
        required_request_fields = []
        request_fields = manifest.get("request_fields", {})
        if isinstance(request_fields, dict):
            for fname, fdef in request_fields.items():
                if isinstance(fdef, dict) and fdef.get("required"):
                    required_request_fields.append(fname)
        # Also check schema fields for request body
        for fname, fdef in fields.items():
            if fname == "id" or not isinstance(fdef, dict):
                continue
            if (
                fdef.get("required")
                and fname not in required_request_fields
                and (fname in ("body", "payload") or fdef.get("in") == "body")
            ):
                required_request_fields.append(fname)

        template_src = self._load_template("route_tests.py.j2")
        template = self._env.from_string(template_src)
        code = template.render(
            component_id=component_id,
            class_name=class_name,
            method=method,
            path=path,
            expected_status=expected_status,
            auth_required=auth_required,
            error_responses=error_responses,
            required_request_fields=required_request_fields,
        )

        test_count = code.count("\n    def test_")

        parsed_name = component_id.split(":", 2)[-1] if ":" in component_id else component_id
        file_slug = _slugify(parsed_name)
        test_file_path = f"tests/generated/test_{file_slug}.py"

        return GeneratedTest(
            component_id=component_id,
            test_code=code,
            test_file_path=test_file_path,
            test_count=test_count,
        )

    def generate_from_error(self, manifest: dict[str, Any], schema: dict[str, Any]) -> GeneratedTest:
        """Generate test code for an error shape component."""
        component_id = manifest.get("id", "unknown")
        class_name = _class_name_from_id(component_id)
        fields = schema.get("fields", {})

        # Build shape fields
        shape_fields = []
        required_shape_fields = []
        sample_error: dict[str, Any] = {}
        for fname, fdef in fields.items():
            if fname == "id" or not isinstance(fdef, dict):
                continue
            ftype = fdef.get("type", "string")
            shape_fields.append(_ShapeField(name=fname, type=ftype))
            if fdef.get("required"):
                required_shape_fields.append(fname)
            # Build sample
            if ftype == "string":
                sample_error[fname] = f"sample_{fname}"
            elif ftype == "integer":
                sample_error[fname] = 0
            elif ftype == "boolean":
                sample_error[fname] = False
            elif ftype in ("list", "ref_list"):
                sample_error[fname] = []
            elif ftype == "map":
                sample_error[fname] = {}
            else:
                sample_error[fname] = ""

        template_src = self._load_template("error_tests.py.j2")
        template = self._env.from_string(template_src)
        code = template.render(
            component_id=component_id,
            class_name=class_name,
            shape_fields=shape_fields,
            required_shape_fields=required_shape_fields,
            sample_error=sample_error,
        )

        test_count = code.count("\n    def test_")

        parsed_name = component_id.split(":", 2)[-1] if ":" in component_id else component_id
        file_slug = _slugify(parsed_name)
        test_file_path = f"tests/generated/test_{file_slug}.py"

        return GeneratedTest(
            component_id=component_id,
            test_code=code,
            test_file_path=test_file_path,
            test_count=test_count,
        )

    def generate_go_from_test(self, manifest: dict[str, Any]) -> GeneratedTest:
        """Generate a Go table-test stub file (one failing subtest per case) from a ydk:test manifest."""
        component_id = manifest.get("id", "unknown")
        name_part = component_id.split(":", 2)[-1]
        namespace, _, base = name_part.rpartition("/")
        base, _, level_suffix = base.partition(".")
        level = str(manifest.get("level") or level_suffix)
        suffix = "" if level in ("", "unit") else "_" + level
        package = _go_package(namespace.rsplit("/", 1)[-1])
        target = str(manifest.get("target") or "").rsplit("/", 1)[-1] or base
        ident = re.sub(r"[^a-zA-Z0-9]", "", target)
        func_name = "Test" + ident[:1].upper() + ident[1:] + suffix.replace("_", "").capitalize()
        cases = [
            {
                "name_literal": json.dumps(str(c["name"]), ensure_ascii=False),
                "comments": "\n".join(
                    _go_comment(label, c.get(key))
                    for label, key in (("Given", "given"), ("When", "when"), ("Then", "then"))
                ),
            }
            for c in self._go_cases(manifest)
        ]
        template = self._env.from_string(self._load_template("go_test.go.j2"))
        code = template.render(
            build_tag="integration" if manifest.get("level") == "integration" else "",
            package=package,
            func_name=func_name,
            cases=cases,
        )
        dirs = [d for d in (_path_segment(seg) for seg in namespace.split("/")) if d]
        stem = _path_segment(base)
        if stem != base:
            digest = hashlib.sha256(component_id.encode("utf-8")).hexdigest()[:8]
            stem = f"{stem or 'tests'}_{digest}"
        file_name = f"{stem}{suffix}_test.go"
        path = "/".join([*dirs, file_name])
        return GeneratedTest(component_id=component_id, test_code=code, test_file_path=path, test_count=len(cases))

    @staticmethod
    def _go_cases(manifest: dict[str, Any]) -> list[dict[str, Any]]:
        return [c for c in manifest.get("cases") or [] if isinstance(c, dict) and c.get("name")]

    def missing_go_cases(self, manifest: dict[str, Any], existing_code: str) -> list[str]:
        """Return manifest case names with no subtest in ``existing_code``.

        Covered when ``t.Run`` is called with the name as a "..." or `...` literal, or when the file
        calls ``t.Run`` with a non-literal name (table-driven) and the case name appears as a table
        entry (``field: "name"`` or ``{"name", ...}``).
        """
        dynamic_run = re.search(r"t\.Run\(\s*[A-Za-z_]", existing_code) is not None
        missing = []
        for c in self._go_cases(manifest):
            name = str(c["name"])
            lits = [re.escape(json.dumps(name, ensure_ascii=False)), "`" + re.escape(name) + "`"]
            alt = "(?:" + "|".join(lits) + ")"
            if re.search(r"t\.Run\(\s*" + alt, existing_code):
                continue
            if dynamic_run and re.search(r"(?:[:{,]\s*)" + alt, existing_code):
                continue
            missing.append(name)
        return missing


_GO_KEYWORDS = frozenset(
    [
        "break",
        "case",
        "chan",
        "const",
        "continue",
        "default",
        "defer",
        "else",
        "fallthrough",
        "for",
        "func",
        "go",
        "goto",
        "if",
        "import",
        "interface",
        "map",
        "package",
        "range",
        "return",
        "select",
        "struct",
        "switch",
        "type",
        "var",
    ]
)


def check_path_collisions(results: list[GeneratedTest]) -> None:
    """Raise ValueError naming both manifest ids when two results share an output path."""
    seen: dict[str, str] = {}
    for r in results:
        if r.test_file_path in seen:
            raise ValueError(f"{seen[r.test_file_path]} and {r.component_id} both resolve to {r.test_file_path}")
        seen[r.test_file_path] = r.component_id


def _go_package(segment: str) -> str:
    """Sanitize a namespace segment into a valid lowercase Go package identifier."""
    pkg = re.sub(r"[^a-z0-9_]", "_", segment.lower()).strip("_") or "tests"
    if pkg[0].isdigit():
        pkg = "p" + pkg
    return pkg + "_" if pkg in _GO_KEYWORDS else pkg


def _path_segment(text: str) -> str:
    """Make one path segment safe for any OS: no separators, colons, dots-only or whitespace."""
    seg = re.sub(r"[^A-Za-z0-9_-]", "_", text).strip("_")
    return seg


def _go_comment(label: str, text: object) -> str:
    lines = str(text or "").splitlines() or [""]
    out = [f"\t\t// {label}: {lines[0]}".rstrip()]
    out += [f"\t\t// {ln}".rstrip() for ln in lines[1:]]
    return "\n".join(out)

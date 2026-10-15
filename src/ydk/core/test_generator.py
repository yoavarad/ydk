"""Test generator — produces Python test code from component manifests."""

from __future__ import annotations

import json
import re
import warnings
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
        namespace, base, suffix, func_name = _go_test_identity(manifest)
        package = _go_package(namespace.rsplit("/", 1)[-1])
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
        skipped = [d for d in dirs if d[0] in "_." or d == "testdata"]
        if skipped:
            warnings.warn(
                f"Go ignores directories starting with '_' or '.' or named testdata ({', '.join(skipped)}); "
                f"'go test ./...' will skip {'/'.join(dirs)}/",
                stacklevel=2,
            )
        file_name = f"{_path_segment(base).lstrip('_.') or 'tests'}{suffix}_test.go"
        path = "/".join([*dirs, file_name])
        return GeneratedTest(component_id=component_id, test_code=code, test_file_path=path, test_count=len(cases))

    @staticmethod
    def _go_cases(manifest: dict[str, Any]) -> list[dict[str, Any]]:
        return [c for c in manifest.get("cases") or [] if isinstance(c, dict) and c.get("name")]

    def missing_go_cases(self, manifest: dict[str, Any], existing_code: str) -> list[str]:
        """Return manifest case names with no subtest in ``existing_code``.

        Covered when ``t.Run`` is called with the name as a "..." or `...` literal, or when the file
        calls ``t.Run`` with a non-literal name (table-driven) and the case name is a ``name:`` field
        (or leading unkeyed element) of the composite literal ranged over by the ``for ... range`` loop.
        Comments are ignored.
        """
        code = _strip_go_comments(existing_code)
        table = _go_range_tables(code, _go_test_identity(manifest)[3])
        missing = []
        for c in self._go_cases(manifest):
            name = str(c["name"])
            lits = [re.escape(json.dumps(name, ensure_ascii=False)), "`" + re.escape(name) + "`"]
            alt = "(?:" + "|".join(lits) + ")"
            if re.search(r"t\.Run\(\s*" + alt, code):
                continue
            if table and re.search(r"(?:\bname\s*:|\{)\s*" + alt, table):
                continue
            missing.append(name)
        return missing


def _go_test_identity(manifest: dict[str, Any]) -> tuple[str, str, str, str]:
    """Return ``(namespace, base, level suffix, Go test func name)`` for a ydk:test manifest."""
    name_part = str(manifest.get("id", "unknown")).split(":", 2)[-1]
    namespace, _, base = name_part.rpartition("/")
    base, _, level_suffix = base.partition(".")
    level = str(manifest.get("level") or level_suffix)
    suffix = "" if level in ("", "unit") else "_" + level
    target = str(manifest.get("target") or "").rsplit("/", 1)[-1] or base
    return namespace, base, suffix, "Test" + _go_camel(target) + _go_camel(suffix)


def _go_string_end(code: str, i: int) -> int:
    """Index just past the Go string/rune literal starting at ``code[i]``."""
    quote = code[i]
    j = i + 1
    while j < len(code) and code[j] != quote:
        j += 2 if quote != "`" and code[j] == "\\" else 1
    return j + 1


def _strip_go_comments(code: str) -> str:
    out: list[str] = []
    i, n = 0, len(code)
    while i < n:
        ch = code[i]
        if ch in "\"`'":
            j = min(_go_string_end(code, i), n)
            out.append(code[i:j])
            i = j
        elif code.startswith("//", i):
            while i < n and code[i] != "\n":
                i += 1
        elif code.startswith("/*", i):
            end = code.find("*/", i + 2)
            i = n if end < 0 else end + 2
            out.append(" ")
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _go_balanced_end(code: str, i: int) -> int:
    """Index just past the ``{...}`` group opening at ``code[i]``."""
    depth = 0
    while i < len(code):
        ch = code[i]
        if ch in "\"`'":
            i = _go_string_end(code, i)
            continue
        depth += (ch == "{") - (ch == "}")
        i += 1
        if depth == 0:
            break
    return i


def _go_blank_nested(literal: str) -> str:
    """Blank content nested deeper than table rows, so only row-level ``name:``/first elements remain."""
    out: list[str] = []
    depth, i = 0, 0
    while i < len(literal):
        ch = literal[i]
        if ch in "\"`'":
            j = _go_string_end(literal, i)
            out.append(literal[i:j] if depth <= 2 else " ")
            i = j
            continue
        if ch == "{":
            depth += 1
            out.append(ch if depth <= 2 else " ")
        elif ch == "}":
            out.append(ch if depth <= 2 else " ")
            depth -= 1
        else:
            out.append(ch if depth <= 2 else " ")
        i += 1
    return "".join(out)


_GO_TOP_LEVEL = re.compile(r"^(?=(?:func|var|const|type)\b)", re.MULTILINE)
_GO_FUNC_START = re.compile(r"func\b")


def _go_range_tables(code: str, func_name: str) -> str:
    """Composite-literal bodies of the tables ranged over in each test function.

    A ``range X`` / ``range a.b.X`` target is resolved to a declaration (``X :=``, ``X =``,
    ``var X = ...`` or ``var X T = ...``) in the enclosing function first, then at package level.
    Tables of other functions are never consulted; selector roots are not resolved (last name only).
    Only ``func_name`` is inspected when the file defines it, otherwise every function is.
    """
    segments = _GO_TOP_LEVEL.split(code)
    pkg_level = "\n".join(sg for sg in segments if not _GO_FUNC_START.match(sg))
    bodies: list[str] = []
    funcs = [sg for sg in segments if _GO_FUNC_START.match(sg)]
    own = [sg for sg in funcs if re.match(r"func\s+" + re.escape(func_name) + r"\b", sg)]
    for fn in own or funcs:
        if re.search(r"t\.Run\(\s*[A-Za-z_]", fn) is None:
            continue
        targets = re.findall(r"\bfor\b[^{\n]*?\brange\s+(?:[A-Za-z_]\w*\s*\.\s*)*([A-Za-z_]\w*)\s*\{", fn)
        for tbl in dict.fromkeys(targets):
            decl = re.compile(r"\b" + re.escape(tbl) + r"(?:\s*(?::=|=(?!=))|[ \t]+[^\n=]*?=(?!=))\s*[^\n{]*(?=\{)")
            scope = fn if decl.search(fn) else pkg_level
            for m in decl.finditer(scope):
                start = end = m.end()
                while True:  # skip brace groups of the element type (``struct{...}``) up to the value literal
                    end = _go_balanced_end(scope, end)
                    nxt = re.match(r"\s*(?=\{)", scope[end:])
                    if not nxt:
                        break
                    end += nxt.end()
                bodies.append(_go_blank_nested(scope[start:end]))
    return "\n".join(bodies)


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


def _go_package(segment: str) -> str:
    """Sanitize a namespace segment into a valid lowercase Go package identifier."""
    pkg = re.sub(r"[^a-z0-9_]", "_", segment.lower()).strip("_") or "tests"
    if pkg[0].isdigit():
        pkg = "p" + pkg
    return pkg + "_" if pkg in _GO_KEYWORDS else pkg


def _go_camel(text: str) -> str:
    """CamelCase on non-alphanumeric boundaries, keeping inner capitals; a letter after a digit is upper-cased."""
    words = (w for w in re.split(r"[^a-zA-Z0-9]+", text) if w)
    return re.sub(r"(?<=\d)[a-z]", lambda m: m.group().upper(), "".join(w[:1].upper() + w[1:] for w in words))


def _path_segment(text: str) -> str:
    """Make one path segment safe for any OS; keeps valid leading '_' and inner '.', drops dots-only."""
    seg = re.sub(r"[^A-Za-z0-9_.-]", "_", text).rstrip(".")
    return seg


def _go_comment(label: str, text: object) -> str:
    lines = str(text or "").splitlines() or [""]
    out = [f"\t\t// {label}: {lines[0]}".rstrip()]
    out += [f"\t\t// {ln}".rstrip() for ln in lines[1:]]
    return "\n".join(out)
